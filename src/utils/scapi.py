import aiohttp


class StalcraftAPI:
    def __init__(self, client_id, client_secret, auth_token, url="https://eapi.stalcraft.net/",
                 debug=False,
                 stalcraft_status_key=None,
                 stalcraft_status_url='https://stalcraft-status.ru/',
                 demo_url='https://dapi.stalcraft.net/'
                 ):
        self.__api_url = url if not debug else demo_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.debug = debug
        self.stalcraft_status_key = stalcraft_status_key
        self.stalcraft_status_url = stalcraft_status_url
        self.appToken = auth_token
        self.authHeader = {"Authorization": f"Bearer {self.appToken}"}
        self.session = aiohttp.ClientSession()


    async def __request_get(self, endpoint, headers=None, apiUrl=None, method='get'):
        apiUrl = apiUrl if apiUrl else self.__api_url
        url = apiUrl + endpoint
        if method == 'post':
            async with self.session.post(url, data=headers) as resp:
                r = await resp.json()
        else:
            async with self.session.get(url, headers=headers) as resp:
                r = await resp.json()
        return r
    
    #No stalcraft api
    async def get_stalcraft_online(self):
        if not self.stalcraft_status_key:
            return 0
        try:
            endpoint = 'api/v1/last'
            params = f'?token={self.stalcraft_status_key}&v=2'
            endpoint += params
            r = await self.__request_get(endpoint, apiUrl=self.stalcraft_status_url)
            return int(r.get('online'))
        except Exception as e:
            print(e)
            return 0
    
    async def get_regions(self):
        endpoint = 'regions'
        r = await self.__request_get(endpoint, self.authHeader)
        return r

    async def get_auction_history(self, item_id, region, additional="true", limit=100, offset=0):
        endpoint = f'{region}/auction/{item_id}/history'
        params = f'?limit={limit}&additional={additional}&offset={offset}'
        endpoint += params
        r = await self.__request_get(endpoint, self.authHeader)
        return r

    async def get_auction_lots(self, item_id, region, additional="true",
                               limit=20, offset=0, select="buyout_price", order=True):
        if order:
            sorder = "asc"
        else:
            sorder = "desc"
        endpoint = f'{region}/auction/{item_id}/lots'
        params = f'?limit={limit}&sort={select}&offset={offset}&order={sorder}&additional={additional}'
        endpoint += params
        r = await self.__request_get(endpoint, self.authHeader)
        return r

    async def get_emission(self, region):
        endpoint = f'{region}/emission'
        r = await self.__request_get(endpoint, self.authHeader)
        return r

    async def run(self):
        if self.debug:
            return True
        endpoint = 'oauth/token'
        headers = {
            "client_id": str(self.client_id),
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        r = await self.__request_get(endpoint, headers, apiUrl='https://exbo.net/', method='post')
        self.appToken = r.get('access_token')
        self.authHeader = {"Authorization": f"Bearer {self.appToken}"}
        return r

    async def close(self):
        await self.session.close()
