import os
import json
import logging
import argparse

import cloudminer.utils as utils
from cloudminer.logger import logger
from cloudminer.exceptions import CloudMinerException
from azure_automation_session import AzureAutomationSession
from scripts_executor import PowershellScriptExecutor, PythonScriptExecutor


def get_access_token_from_cli() -> str:
    """
    使用 Azure CLI 获取 Azure 访问令牌

    :raises CloudMinerException: 如果未安装 Azure CLI 或未设置 PATH 环境变量
                                 如果账户未通过 Azure CLI 登录
                                 如果无法获取账户访问令牌
    """
    logger.info("使用 Azure CLI 获取访问令牌...")
    try:
        # 检查用户是否已登录
        process = utils.run_command(["az", "account", "show"])
        if process.returncode != 0:
            raise CloudMinerException(f"必须通过 Azure CLI 登录账户")
        
        process = utils.run_command(["az", "account", "get-access-token"])
        if process.returncode != 0:
            raise CloudMinerException(f"使用 Azure CLI 获取访问令牌失败。错误信息：{process.stderr}")
         
    except FileNotFoundError:
        raise CloudMinerException("系统中未安装 Azure CLI 或未设置 PATH 环境变量")

    return json.loads(process.stdout)["accessToken"]
    

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数
    """
    parser = argparse.ArgumentParser(description="CloudMiner - Azure 自动化服务中的免费计算资源")
    parser.add_argument("--path", type=str, help="脚本路径（Powershell 或 Python）", required=True)
    parser.add_argument("--id", type=str, help="自动化帐户的 ID - /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Automation/automationAccounts/{automationAccountName}", required=True)
    parser.add_argument("-c","--count", type=int, help="执行次数", required=True)
    parser.add_argument("-t","--token", type=str, help="Azure 访问令牌（可选）。如果不提供，将使用 Azure CLI 获取访问令牌")
    parser.add_argument("-r","--requirements", type=str, help="要安装并由脚本使用的要求文件的路径（仅适用于 Python 脚本）")
    parser.add_argument('-v', '--verbose', action='store_true', help='启用详细模式')
    return parser.parse_args()


def main():
    args = parse_args()
    level = logging.DEBUG if args.verbose else logging.INFO
    logger.setLevel(level)
    logger.info(utils.PROJECT_BANNER)
    
    if not os.path.exists(args.path):
        raise CloudMinerException(f"脚本路径 '{args.path}' 不存在！")
    
    if args.requirements and not os.path.exists(args.requirements):
        raise CloudMinerException(f"要求文件路径 '{args.requirements}' 不存在！")
    
    access_token = args.token or get_access_token_from_cli()
    automation_session = AzureAutomationSession(args.id, access_token)

    file_extension = utils.get_file_extension(args.path).lower()
    if file_extension == PowershellScriptExecutor.EXTENSION:
        logger.info(f"检测到文件类型 - Powershell")
        executor = PowershellScriptExecutor(automation_session, args.path)

    elif file_extension == PythonScriptExecutor.EXTENSION:
        logger.info(f"检测到文件类型 - Python")
        executor = PythonScriptExecutor(automation_session, args.path, args.requirements)

    else:
        raise CloudMinerException(f"不支持的文件扩展名：{file_extension}")

    
    executor.execute_script(args.count)
    
    logger.info("CloudMiner 成功完成 :)")

if __name__ == "__main__":
    main()
