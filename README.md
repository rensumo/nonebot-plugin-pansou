<div align="center">
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>

## ✨ nonebot-plugin-quark ✨

<a href="./LICENSE">
    <img src="https://img.shields.io/github/license/fllesser/nonebot-plugin-quark.svg" alt="license">
</a>
</div>



## 📖 介绍

网盘资源搜索插件

## 💿 安装

将nonebot-plugin-pansou文件夹下载后修改env的plugin_dirs为"nonebot-plugin-pansou"
然后将__init__.py中的
```python
API_URL = "http://xxx.xxx.xxx/api/search"  # 搜索接口地址
HEALTH_API_URL = "http://xxx.xxx.xxx/api/health"  # 健康检查接口地址
```
改为[盘搜](https://github.com/fish2018/pansou)的访问地址

## 🎉 使用
### 指令表
| 指令 | 权限 | 需要@ | 范围 | 说明 |
|:-----:|:----:|:----:|:----:|:----:|
| pansou | 群员 | 否 | - | 搜索 |
| 盘搜 | 群员 | 否 | - | 搜索 |
