# 云矿机
在 Azure 自动化服务中执行代码而无需付费

## 描述
CloudMiner 是一款旨在在 Azure 自动化服务中获取免费计算能力的工具。该工具利用上传模块/包流程来执行完全免费使用的代码。该工具仅用于教育和研究目的，应负责任地使用并获得适当的授权。

* 此流程已于 3 月 23 日向 Microsoft 报告，微软决定不更改服务行为，因为它被认为是“设计使然”。截至23年3月9日，该工具仍然可以免费使用。

* 每次执行时间限制为3小时

## 要求
1. Python 3.8+ 以及文件中提到的库 `requirements.txt`
2. 配置的 Azure CLI - https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
    - 使用此工具之前必须先登录帐户

## 安装
```pip install .```

## 用法
```
用法: cloud_miner.py [-h] --path PATH --id ID -c COUNT [-t TOKEN] [-r REQUIREMENTS] [-v]

CloudMiner - Azure 自动化服务中的免费计算资源

可选参数:
-h, --help            显示帮助信息并退出
--path 路径           脚本路径（Powershell 或 Python）
--id ID               自动化帐户的 ID - /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.Automation/automationAccounts/{automationAccountName}
-c COUNT, --count COUNT
                      执行次数
-t TOKEN, --token TOKEN
                      Azure 访问令牌（可选）。如果不提供，将使用 Azure CLI 获取访问令牌
-r REQUIREMENTS, --requirements REQUIREMENTS
                      要安装并由脚本使用的要求文件的路径（仅适用于 Python 脚本）
-v, --verbose         启用详细模式
```

## 用法示例
### Python
![Alt text](images/cloud-miner-usage-python.png?raw=true "Usage Example")
### Powershell
![Alt text](images/cloud-miner-usage-powershell.png?raw=true "Usage Example")
