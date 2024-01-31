import os
import time
import uuid
import shutil
from typing import List
from abc import ABC, abstractmethod

import cloudminer.utils as utils
from cloudminer.logger import logger
from cloudminer.exceptions import CloudMinerException
from azure_automation_session import UPLOAD_STATE, UPLOAD_TIMEOUT, AzureAutomationSession


class ScriptExecutor(ABC):

    EXTENSION: str

    def __init__(self, automation_session: AzureAutomationSession, script_path: str) -> None:
        """
        :param automation_session: 使用的自动化帐户会话
        :param script_path: 在自动化帐户中执行的脚本
        """
        super().__init__()
        self.automation_session = automation_session
        self.script_path = script_path

    @abstractmethod
    def execute_script(self, count: int):
        """
        在 Azure 自动化中执行脚本

        :param count: 执行次数
        """
        pass


class PowershellScriptExecutor(ScriptExecutor):

    EXTENSION = ".ps1"

    def execute_script(self, count: int):
        """
        在 Azure 自动化中执行 Powershell 模块

        :param count: 执行次数
        """
        for index in range(count):
            logger.info(f"触发 Powershell 执行 - {index+1}/{count}:")
            logger.add_indent()
            module_name = str(uuid.uuid4())
            zipped_ps_module = utils.zip_file(self.script_path, f"{module_name}.psm1")
            self.automation_session.upload_powershell_module(module_name, zipped_ps_module)
            logger.info(f"在自动化帐户中触发模块导入流程。代码执行将在几分钟后触发...")
            logger.remove_indent()


class PythonScriptExecutor(ScriptExecutor):
    """
    执行 Python 脚本的 ScriptExecutor 类
    """
    EXTENSION = ".py"
    PIP_PACKAGE_NAME = "pip"
    UPLOAD_STATE_CHECK_INTERVAL_SECONDS = 20
    CUSTOM_PIP_PATH = os.path.join(utils.RESOURCES_DIRECTORY, PIP_PACKAGE_NAME)
    DUMMY_WHL_PATH = os.path.join(utils.RESOURCES_DIRECTORY, "random_whl-0.0.1-py3-none-any.whl")
    
    def __init__(self, automation_session: AzureAutomationSession, script_path: str, requirements_file: str = None) -> None:
        """
        :param automation_session: 使用的自动化帐户会话
        :param script_path: 在自动化帐户中执行的脚本
        :param requirements_path: 要安装和使用脚本的要求文件的路径
        """
        super().__init__(automation_session, script_path)
        self.requirements_file = requirements_file

    def _delete_pip_if_exists(self):
        """
        验证 'pip' 包是否存在

        :param delete_if_exists: 如果为 True 并且包存在，则删除该包

        :raises CloudMinerException: 如果包存在且 'delete_if_exists' 为 False
        """
        pip_package = self.automation_session.get_python_package(PythonScriptExecutor.PIP_PACKAGE_NAME)
        if pip_package:
            logger.warning(f"在自动化帐户中已存在包 '{PythonScriptExecutor.PIP_PACKAGE_NAME}'。正在删除包")
            self.automation_session.delete_python_package(PythonScriptExecutor.PIP_PACKAGE_NAME)

    def _wait_for_package_upload(self, package_name: str, timeout_seconds: int = UPLOAD_TIMEOUT):
        """
        等待直到软件包上传流程完成或超时（阻塞）

        :param package_name: 要等待的 Python 包名称
        :param timeout_seconds: 等待上传的最大时间

        :raises CloudMinerException: 如果给定包的上传流程尚未开始
                                     如果上传流程已完成但出现错误
                                     如果达到了超时时间
        """
        logger.info(f"等待软件包完成上传。这可能需要几分钟...")
        logger.add_indent()
        start_time = time.time()
        end_time = start_time + timeout_seconds
        while time.time() < end_time:
            package_data = self.automation_session.get_python_package(package_name)
            if not package_data:
                raise CloudMinerException(f"软件包 '{package_name}' 的上传流程启动失败")
            
            upload_state = package_data["properties"]["provisioningState"]         
            if upload_state == UPLOAD_STATE.SUCCEEDED:
                logger.remove_indent()
                break
            elif upload_state == UPLOAD_STATE.FAILED:
                error = package_data["properties"]["error"]["message"]
                raise CloudMinerException("Python 软件包上传失败。错误：", error)
            else:
                logger.debug(f"上传状态 - '{upload_state}'")
                time.sleep(PythonScriptExecutor.UPLOAD_STATE_CHECK_INTERVAL_SECONDS)
        else:
            raise CloudMinerException("由于超时，Python 软件包上传失败")
        
    def _wrap_script(self) -> List[str]:
        """
        构造安装 Python 包的代码行
        """
        INSTALL_REQUIREMENTS_CODE = []
        if self.requirements_file:
            with open(self.requirements_file, 'r') as f:
                requirements = [line.replace('\n', '') for line in f.readlines()]
                INSTALL_REQUIREMENTS_CODE = ["import requests, subprocess, sys, os, tempfile",
                                            "tmp_folder = tempfile.gettempdir()",
                                            "sys.path.append(tmp_folder)",
                                            "tmp_pip = requests.get('https://bootstrap.pypa.io/get-pip.py').content",
                                            "open(os.path.join(tmp_folder, 'tmp_pip.py'), 'wb+').write(tmp_pip)",
                                            f"subprocess.run(f'{{sys.executable}} {{os.path.join(tmp_folder, \"tmp_pip.py\")}} {' '.join(requirements)} --target {{tmp_folder}}', shell=True)"]
            
        return '\n'.join(["# CloudMiner 自动添加",
                          "######################################################################################"] +
                          INSTALL_REQUIREMENTS_CODE +
                          ["def _main():\n\tpass",
                          "######################################################################################\n"])
        

    def _create_whl_for_upload(self) -> str:
        """
        使用给定的 Python 脚本创建 Python 包 whl

        :raises CloudMinerException: 如果无法创建 .whl 文件
        """
        main_file_path = os.path.join(PythonScriptExecutor.CUSTOM_PIP_PATH, "src", PythonScriptExecutor.PIP_PACKAGE_NAME, "main.py")
        shutil.copyfile(self.script_path, main_file_path)

        # 为文件添加一个主函数，作为入口点
        with open(main_file_path, 'r') as f:
            raw_main_file = f.read()
        
        wrapped_main_file = self._wrap_script() + raw_main_file

        with open(main_file_path, 'w') as f:
            f.write(wrapped_main_file)
            
        return utils.package_to_whl(PythonScriptExecutor.CUSTOM_PIP_PATH)

    def execute_script(self, count: int):
        """
        在 Azure 自动化中执行 Python 脚本

        :param script_path: .whl 文件路径。使用 'prepare_file_for_upload' 获取
        :param count: 执行次数
        """
        self._delete_pip_if_exists()
        whl_path = self._create_whl_for_upload()
        logger.info(f"替换自动化帐户中默认的 'pip' 包:")
        logger.add_indent()
        self.automation_session.upload_python_package(PythonScriptExecutor.PIP_PACKAGE_NAME, whl_path)
        self._wait_for_package_upload(PythonScriptExecutor.PIP_PACKAGE_NAME)
        logger.remove_indent()

        logger.info("成功替换 pip 包！")
        for index in range(count):
            logger.info(f"触发 Python 执行 - {index+1}/{count}:")
            logger.add_indent()
            package_name = str(uuid.uuid4())
            self.automation_session.upload_python_package(package_name, PythonScriptExecutor.DUMMY_WHL_PATH)
            logger.info(f"代码执行将在几分钟后触发...")
            logger.remove_indent()
