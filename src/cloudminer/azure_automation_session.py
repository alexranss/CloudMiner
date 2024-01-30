import os
import time
import requests
import posixpath
import urllib.parse
from enum import Enum
from http import HTTPStatus
from datetime import datetime
from datetime import timedelta
from requests.exceptions import ReadTimeout, ChunkedEncodingError

from cloudminer.logger import logger
from cloudminer.exceptions import CloudMinerException

URL_GET_STORAGE_BLOB = "https://s2.automation.ext.azure.com/api/Orchestrator/GenerateSasLinkUri?accountId={account_id}&assetType=Module"
AZURE_MANAGEMENT_URL = "https://management.azure.com"
DEFAULT_API_VERSION = "2018-06-30"
UPLOAD_TIMEOUT = 300
SLEEP_BETWEEN_ERROR_SECONDS = 10
TIME_BETWEEN_REQUESTS_SECONDS = 0.5
TEMP_STORAGE_VALID_SAFETY_SECONDS = 60
HTTP_REQUEST_TIMEOUT = 5

class UPLOAD_STATE(str, Enum):
    """
    Package/Module upload state
    """
    FAILED = "Failed"
    CREATING = "Creating"
    SUCCEEDED = "Succeeded"
    CONTENT_VALIDATED = "ContentValidated"
    CONTENT_DOWNLOADED = "ContentDownloaded"
    CONNECTION_TYPE_IMPORTED = "ConnectionTypeImported"
    RUNNING_IMPORT_MODULE_RUNBOOK = "RunningImportModuleRunbook"

class AzureAutomationSession:
    """
    Represents a session of Azure Automation
    """
    def __init__(self, account_id: str, access_token: str) -> None:
        """
        初始化 Azure Automation 会话
        验证 Automation Account 是否存在，验证访问令牌是否有效

        :param account_id: Automation account ID - /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Automation/automationAccounts/{automationAccountName}
        :param access_token: Azure 访问令牌

        :raises CloudMinerException: 如果提供的访问令牌无效
                                     如果 Automation Account ID 无效
                                     如果提供的 Automation Account 不存在
        """
        self.__account_id = account_id
        self.__access_token = access_token
        self.__next_request_time = 0
        try:
            self.__http_request("GET", self.__get_url())
            logger.info("访问令牌有效")
        except requests.HTTPError as e:
            if e.response.status_code == HTTPStatus.UNAUTHORIZED:
                raise CloudMinerException("提供的访问令牌无效") from e
            if e.response.status_code == HTTPStatus.BAD_REQUEST:
                raise CloudMinerException(f"提供的 Automation Account ID 无效 - '{account_id}'") from e
            if e.response.status_code == HTTPStatus.NOT_FOUND:
                raise CloudMinerException(f"Automation Account 不存在 - '{account_id}'") from e
            raise

    def __get_url(self, path: str = "") -> str:
        """
        构造 Automation Account 中给定路径的 URL
        """
        return posixpath.join(AZURE_MANAGEMENT_URL,
                              self.__account_id[1:],
                              path) + f"?api-version={DEFAULT_API_VERSION}"

    def __wait_for_next_request(self):
        """
        辅助函数，确保在每个请求之前等待一段时间
        """
        current_time = time.time()
        time_gap = self.__next_request_time - current_time
        if time_gap > 0:
            time.sleep(time_gap)

        self.__next_request_time = time.time() + TIME_BETWEEN_REQUESTS_SECONDS

    def __http_request(self,
                     http_method: str,
                     url: str,
                     headers: dict = None,
                     add_auth_info: bool = True,
                     retries: int = 5,
                     timeout: int = HTTP_REQUEST_TIMEOUT,
                     **kwargs) -> requests.Response:
        """
        安全地向 Azure 服务发出 HTTP 请求

        :param http_method:   请求的 HTTP 方法
        :param url:           请求的 URL
        :param headers:       请求的头部信息
        :param authorization: 如果为 True，则设置 'Authorization' 头部信息
        :param retries:       在服务器响应错误时的重试次数
        :return:              响应对象

        :raises HTTPError: 如果收到错误响应
        """
        self.__wait_for_next_request()

        if headers is None:
            headers = {}
            
        if add_auth_info:
            headers["Authorization"] = f"Bearer {self.__access_token}"
        
        for _ in range(retries):
            resp = None
            try:
                resp = requests.request(http_method, url, headers=headers, timeout=timeout, **kwargs)
            except (ReadTimeout, ChunkedEncodingError, ConnectionError): # 从服务器收到错误响应
                pass
            
            if resp is None or resp.status_code in [HTTPStatus.TOO_MANY_REQUESTS,
                                                    HTTPStatus.GATEWAY_TIMEOUT,
                                                    HTTPStatus.SERVICE_UNAVAILABLE]:
                
                logger.warning(f"请求过多。{SLEEP_BETWEEN_ERROR_SECONDS} 秒后重试...")
                time.sleep(SLEEP_BETWEEN_ERROR_SECONDS)
            else:
                resp.raise_for_status()
                return resp
        else:
            raise CloudMinerException(f"发送 HTTP 请求失败 - 达到最大重试次数。"\
                                      f"方法 - '{http_method}', URL - '{url}'")

    def __upload_file_to_temp_storage(self, file_path: str) -> str:
        """
        创建临时存储并上传文件

        :param file_path: 要上传的文件路径
        :return: 临时存储的 URL
        """
        url = URL_GET_STORAGE_BLOB.format(account_id=self.__account_id)
        self.__current_temp_storage_url = self.__http_request("GET", url).json()
        logger.debug("成功创建临时 blob 存储")

        with open(file_path, "rb") as f:
            file_data = f.read()
            
        self.__http_request("PUT",
                            self.__current_temp_storage_url,
                            headers={"x-ms-blob-type": "BlockBlob"},
                            add_auth_info=False,
                            data=file_data)
        
        file_name = os.path.basename(file_path)
        logger.debug(f"文件 '{file_name}' 已上传到临时存储")
        return self.__current_temp_storage_url

    def upload_powershell_module(self, module_name: str, zipped_ps_module: str):
        """
        将 Powershell 模块上传到 Automation Account
        """
        logger.info(f"正在上传 Powershell 模块 '{module_name}'")
        
        temp_storage_url = self.__upload_file_to_temp_storage(zipped_ps_module)
        url = self.__get_url(f"modules/{module_name}")
        request_data = {
            "properties": {
                "contentLink": {
                    "uri": temp_storage_url
                }
            }
        }
        self.__http_request("PUT", url, json=request_data)

    def upload_python_package(self, package_name: str, whl_path: str):
        """
        从给定的 blob 存储中上传 Python 包
        """
        logger.info(f"正在上传 Python 包 - '{package_name}':")
        
        temp_storage_url = self.__upload_file_to_temp_storage(whl_path)
        url = self.__get_url(f"python3Packages/{package_name}")
        request_data = {
            "properties": {
                "contentLink": {
                    "uri": temp_storage_url
                }
            }
        }
        self.__http_request("PUT", url, json=request_data)
        logger.info(f"在 Automation Account 中触发包导入流程。")

    def get_python_package(self, package_name: str) -> dict:
        """
        检索 Python 包。如果不存在则返回 None
        """
        url = self.__get_url(f"python3Packages/{package_name}")
        try:
            package_data = self.__http_request("GET", url).json()
        except requests.HTTPError as e:
            if e.response.status_code == HTTPStatus.NOT_FOUND:
                return None
            else:
                raise
            
        return package_data
    
    def delete_python_package(self, package_name: str):
        """
        删除 Python 包
        
        :raises CloudMinerException: 如果给定的包不存在
        """
        url = self.__get_url(f"python3Packages/{package_name}")
        try:
            self.__http_request("DELETE", url)
        except requests.HTTPError as e:
            if e.response.status_code == HTTPStatus.NOT_FOUND:
                raise CloudMinerException(f"无法删除包 {package_name}。包不存在")
            else:
                raise
