import asyncio
import random
import time
from datetime import datetime, timezone, timedelta
from logging import exception

import aiogram
import inflect
import pymorphy3
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile

from config import config
from db.models.emissions import Emission
from utils.scapi import StalcraftAPI


groups = config["groups"]
EMISSION_END_TIME = 225
DAMAGE_PHASE_TIME = 120

inflect_engine = inflect.engine()
morph = pymorphy3.MorphAnalyzer()


def pluralize_noun_en(number: int, word: str) -> str:
    return f"{number} {inflect_engine.plural(word, number)}"


def pluralize_noun_ru(number: int, word: str) -> str:
    parsed_word = morph.parse(word)[0]
    pluralized_word = parsed_word.make_agree_with_number(number).word
    return f"{number} {pluralized_word}"


def time_converter_ru(seconds: int) -> str:
    if seconds >= 0:
        if seconds < 60:
            return f"{pluralize_noun_ru(seconds, 'секунда')} назад"
        if seconds < 3600:
            return f"{pluralize_noun_ru(seconds // 60, 'минута')} назад"
        return f"{pluralize_noun_ru(seconds // 3600, 'час')} назад"

    seconds = abs(seconds)
    if seconds < 60:
        return f"через {pluralize_noun_ru(seconds, 'секунда')}"
    if seconds < 3600:
        return f"через {pluralize_noun_ru(seconds // 60, 'минута')}"
    return f"через {pluralize_noun_ru(seconds // 3600, 'час')}"


def time_converter_en(seconds: int) -> str:
    if seconds >= 0:
        if seconds < 60:
            return f"{pluralize_noun_en(seconds, 'second')} ago"
        if seconds < 3600:
            return f"{pluralize_noun_en(seconds // 60, 'minute')} ago"
        return f"{pluralize_noun_en(seconds // 3600, 'hour')} ago"

    seconds = abs(seconds)
    if seconds < 60:
        return f"in {pluralize_noun_en(seconds, 'second')}"
    if seconds < 3600:
        return f"in {pluralize_noun_en(seconds // 60, 'minute')}"
    return f"in {pluralize_noun_en(seconds // 3600, 'hour')}"


def parse_emission_time(raw_time: str) -> tuple[datetime, int]:
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(raw_time, fmt).replace(tzinfo=timezone.utc)
            return dt, int(dt.timestamp())
        except ValueError:
            continue

    raise ValueError(f"Не удалось распарсить время выброса: {raw_time}")


def format_online(region: str, online: int) -> str:
    if region == "RU":
        return str(online) if online > 0 else "не установлен"
    return str(online) if online > 0 else "not received"


async def emission_exists(region: str, emission_timestamp: int):
    return await Emission.find_one(
        Emission.region == region,
        Emission.emission_timestamp == emission_timestamp,
    )


async def process_previous_emission(
    bot: aiogram.Bot,
    region: str,
    group: str,
    raw_start: str,
    online: int,
) -> None:
    _, emission_timestamp = parse_emission_time(raw_start)

    existing_emission = await emission_exists(region, emission_timestamp)
    if existing_emission:
        return

    print(f"Missed previous emission, region: {region}, time: {raw_start}")

    image_path = f"assets/images/emm{random.randint(1, 5)}.png"
    photo = FSInputFile(image_path)

    caption = make_finished_message(
        region=region,
        group=group,
        emission_timestamp=emission_timestamp,
        online=online,
    )

    try:
        msg = await bot.send_photo(
            chat_id=group,
            photo=photo,
            caption=caption,
        )
    except TelegramRetryAfter as e:
        print(f"Telegram просит подождать перед отправкой previous emission: {e}")
        return
    except Exception as e:
        print(f"Ошибка отправки previous emission: {e}")
        return

    new_emission = Emission(
        region=region,
        emission_time=raw_start,
        emission_timestamp=emission_timestamp,
        message_id=msg.message_id,
        group=group,
        last_online=online,
    )
    await new_emission.insert()

    print("INSERTED PREVIOUS:", region, raw_start, emission_timestamp)


def make_message(region: str, group: str, emission_timestamp: int, online: int) -> str:
    now_timestamp = int(time.time())
    passed_time = now_timestamp - emission_timestamp

    damage_time = passed_time - DAMAGE_PHASE_TIME
    safe_time = passed_time - EMISSION_END_TIME
    online_text = format_online(region, online)

    if region == "RU":
        if passed_time < EMISSION_END_TIME:
            return f"""
<b>💥 Выброс начался!</b>

<b>Время начала: </b>{time_converter_ru(passed_time)}
<b>Урон {"начнётся" if damage_time < 0 else "начался"}: </b>{time_converter_ru(damage_time)}
<b>Безопасно будет: </b>{time_converter_ru(safe_time)}
<b>Актуальный онлайн: </b>{online_text}

t.me/{group[1:]}
""".strip()

        spawn_boost_text = ""
        if (passed_time - EMISSION_END_TIME) < 60 * 30:
            spawn_boost_text = "\n<b>Спавн артефактов повышен</b>\n"

        return f"""
<b>💥 Выброс!</b>

<b>Закончился: </b>{time_converter_ru(passed_time - EMISSION_END_TIME)}{spawn_boost_text}
<b>Актуальный онлайн: </b>{online_text}

t.me/{group[1:]}
""".strip()

    if passed_time < EMISSION_END_TIME:
        return f"""
<b>💥 An Eruption occurred!</b>

<b>Start time: </b>{time_converter_en(passed_time)}
<b>Damage begins: </b>{time_converter_en(damage_time)}
<b>Will be safe: </b>{time_converter_en(safe_time)}
<b>Current online: </b>{online_text}

t.me/{group[1:]}
""".strip()

    spawn_boost_text = ""
    if (passed_time - EMISSION_END_TIME) < 60 * 30:
        spawn_boost_text = "\n<b>Artifacts Spawn Boosted</b>\n"

    return f"""
<b>💥 Eruption!</b>

<b>End time: </b>{time_converter_en(passed_time - EMISSION_END_TIME)}{spawn_boost_text}
<b>Current online: </b>{online_text}

t.me/{group[1:]}
""".strip()


def make_finished_message(region: str, group: str, emission_timestamp: int, online: int) -> str:
    dt_utc = datetime.utcfromtimestamp(emission_timestamp)
    dt_msk = dt_utc + timedelta(hours=3)

    if region == "RU":
        return f"""
<b>💥 Выброс!</b>

<b>Время начала: </b>{dt_msk.strftime('%H:%M')} (МСК)
<b>Игроков онлайн: </b>{format_online(region, online)}

t.me/{group[1:]}
""".strip()

    return f"""
<b>💥 Eruption!</b>

<b>Start time: </b>{dt_utc.strftime('%H:%M')} (UTC)
<b>Players online: </b>{format_online(region, online)}

t.me/{group[1:]}
""".strip()


async def send_new_emission_message(
    bot: aiogram.Bot,
    region: str,
    group: str,
    emission_timestamp: int,
    online: int,
) -> aiogram.types.Message | None:
    image_path = f"assets/images/emm{random.randint(1, 5)}.png"
    photo = FSInputFile(image_path)
    caption = make_message(region, group, emission_timestamp, online)

    try:
        return await bot.send_photo(
            chat_id=group,
            photo=photo,
            caption=caption,
        )
    except TelegramRetryAfter as e:
        print(f"Telegram просит подождать перед повторной отправкой: {e}")
    except Exception as e:
        print(f"Ошибка отправки сообщения о выбросе: {e}")

    return None


async def edit_emission_caption(
    bot: aiogram.Bot,
    chat_id: str,
    message_id: int,
    caption: str,
) -> None:
    if not message_id:
        return

    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
        )
    except TelegramBadRequest:
        pass
    except TelegramRetryAfter as e:
        print(f"Telegram просит подождать перед редактированием: {e}")
    except Exception as e:
        print(f"Ошибка редактирования сообщения: {e}")


async def get_last_emission(region: str):
    return await Emission.find(
        Emission.region == region
    ).sort(-Emission.emission_timestamp).first_or_none()


async def process_current_emission(
    bot: aiogram.Bot,
    region: str,
    group: str,
    raw_start: str,
    online: int,
) -> None:
    _, emission_timestamp = parse_emission_time(raw_start)

    existing_emission = await Emission.find_one(
        Emission.region == region,
        Emission.emission_timestamp == emission_timestamp,
    )

    print("REGION:", region)
    print("RAW_START:", raw_start)
    print("EMISSION_TIMESTAMP:", emission_timestamp)
    print("FOUND:", existing_emission)

    if existing_emission:
        return

    previous_emission = await get_last_emission(region)

    print(f"Emission start, region: {region}, time: {raw_start}")

    sent_message = await send_new_emission_message(
        bot=bot,
        region=region,
        group=group,
        emission_timestamp=emission_timestamp,
        online=online,
    )

    if sent_message is None:
        return

    new_emission = Emission(
        region=region,
        emission_time=raw_start,
        emission_timestamp=emission_timestamp,
        message_id=sent_message.message_id,
        group=group,
        last_online=online,
    )
    await new_emission.insert()
    print("INSERTED:", region, raw_start, emission_timestamp)

    if previous_emission:
        finished_caption = make_finished_message(
            region=region,
            group=group,
            emission_timestamp=previous_emission.emission_timestamp,
            online=previous_emission.last_online,
        )
        await edit_emission_caption(
            bot=bot,
            chat_id=previous_emission.group,
            message_id=previous_emission.message_id,
            caption=finished_caption,
        )


async def update_last_emission_message(
    bot: aiogram.Bot,
    region: str,
    group: str,
    online: int,
) -> None:
    last_emission = await get_last_emission(region)

    if not last_emission:
        return

    caption = make_message(region, group, last_emission.emission_timestamp, online)

    await edit_emission_caption(
        bot=bot,
        chat_id=last_emission.group,
        message_id=last_emission.message_id,
        caption=caption,
    )


async def start_loop(bot: aiogram.Bot):
    sc = StalcraftAPI(
        client_id=config["stalcraft_api"]["client_id"],
        client_secret=config["stalcraft_api"]["client_secret"],
        auth_token=config["stalcraft_api"]["auth_token"],
        debug=config["bot"]["debug"],
        stalcraft_status_key=config["stalcraft_api"]["stalcraft_status_key"],
    )

    await sc.run()

    while True:
        try:
            for region, group in groups.items():
                try:
                    emission_data = await sc.get_emission(region)

                    online = await sc.get_stalcraft_online()

                    previous_start = emission_data.get("previousStart")
                    current_start = emission_data.get("currentStart")

                    if previous_start:
                        await process_previous_emission(
                            bot=bot,
                            region=region,
                            group=group,
                            raw_start=previous_start,
                            online=online,
                        )

                    if current_start:
                        await process_current_emission(
                            bot=bot,
                            region=region,
                            group=group,
                            raw_start=current_start,
                            online=online,
                        )

                    await update_last_emission_message(
                        bot=bot,
                        region=region,
                        group=group,
                        online=online,
                    )

                except Exception as e:
                    print(f"Ошибка обработки региона {region}: {e}")

            await asyncio.sleep(config["bot"]["update_time_sec"])

        except Exception as e:
            exception(e)
            await asyncio.sleep(5)