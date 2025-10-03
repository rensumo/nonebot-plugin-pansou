from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Bot  # 兼容旧版NoneBot2的Bot导入路径
from nonebot.adapters.onebot.v11 import MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
import httpx
import json

# ==================== 配置区域 ====================
API_URL = "http://xxx.xxx.xxx/api/search"  # 替换为实际有效接口地址
HEALTH_API_URL = "http://xxx.xxx.xxx/api/health"  # 替换为实际有效接口地址
MAX_MESSAGE_LENGTH = 500  # 单段消息最大长度（仅用于分割，不影响合并转发）
# ==================================================================

# 插件元数据（确保格式符合旧版NoneBot2要求）
__plugin_meta__ = PluginMetadata(
    name="盘搜",
    description="NoneBot2 网盘资源搜索插件（强制合并转发）",
    usage="/盘搜 关键词\n或指定网盘：/盘搜 关键词 百度网盘,阿里云盘",
    type="application",
    homepage="https://github.com/rensumo/nonebot-plugin-pansou",
    supported_adapters={"~onebot.v11"},
)

# 网盘类型映射（核心逻辑不变）
CLOUD_TYPE_MAP = {
    "百度网盘": "baidu",
    "阿里云盘": "aliyun",
    "夸克网盘": "quark",
    "天翼云盘": "tianyi",
    "UC网盘": "uc",
    "移动云盘": "mobile",
    "115网盘": "115",
    "PikPak": "pikpak",
    "迅雷网盘": "xunlei",
    "123网盘": "123",
    "磁力链接": "magnet",
    "电驴链接": "ed2k",
    "其他": "others"
}
PAN_TYPE_MAPPING = {v: k for k, v in CLOUD_TYPE_MAP.items()}
SUPPORTED_CLOUDS = ", ".join(CLOUD_TYPE_MAP.keys())

# 创建命令处理器（兼容旧版优先级和block参数）
pansou = on_command("pansou", aliases={"盘搜"}, priority=5, block=True)
pansou_status = on_command("pansou status", aliases={"盘搜 状态"}, priority=5, block=True)


def split_long_message(message: str, max_length: int = MAX_MESSAGE_LENGTH) -> list:
    """消息分割函数（确保行完整性，兼容长文本）"""
    if len(message) <= max_length:
        return [message]
    
    parts = []
    current_part = ""
    lines = message.split('\n')
    
    for line in lines:
        if len(line) > max_length:
            if current_part:
                parts.append(current_part)
                current_part = ""
            # 长行按空格分割，避免文字截断
            start = 0
            while start < len(line):
                end = start + max_length
                if end < len(line) and line[end] != ' ':
                    last_space = line.rfind(' ', start, end)
                    if last_space != -1:
                        end = last_space + 1
                parts.append(line[start:end].strip())
                start = end
        else:
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part)
                current_part = line
            else:
                current_part = f"{current_part}\n{line}" if current_part else line
    
    if current_part:
        parts.append(current_part)
    return parts


async def send_force_forward_msg(bot: Bot, event: MessageEvent, message: str):
    """强制合并转发函数（无段数判断，失败才回退）"""
    message_parts = split_long_message(message)
    
    # 构建合并转发节点（兼容OneBot.v11协议）
    forward_nodes = [
        MessageSegment.node_custom(
            user_id=event.self_id,  # 机器人自身ID（避免显示异常）
            nickname="盘搜助手",
            content=Message(part)
        ) for part in message_parts
    ]
    
    # 强制执行合并转发
    try:
        await bot.send_forward_msg(
            user_id=event.user_id,
            messages=forward_nodes
        )
    except Exception as e:
        # 仅异常时回退分段，非主动跳过
        await pansou.send(f"合并转发暂不可用（{str(e)[:20]}），分段发送：")
        for i, part in enumerate(message_parts, 1):
            await pansou.send(f"【{i}/{len(message_parts)}】\n{part}")


# ------------------------------ 搜索命令处理 ------------------------------
@pansou.handle()
# 关键：通过依赖注入获取Bot，避免从Matcher取bot（兼容旧版）
async def handle_pansou(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    raw_text = args.extract_plain_text().strip()
    
    # 无参数时直接终止流程（不依赖FinishedException，让NoneBot自动处理）
    if not raw_text:
        await pansou.finish(
            f"格式错误！正确用法：\n"
            f"/盘搜 关键词（例：/盘搜 电影）\n"
            f"/盘搜 关键词 网盘（例：/盘搜 电影 百度网盘,阿里云盘）\n"
            f"支持网盘：{SUPPORTED_CLOUDS}"
        )
    
    # 解析关键词和网盘
    parts = raw_text.rsplit(" ", 1)
    if len(parts) == 2:
        keyword, cloud_input = parts
        cloud_list = [c.strip() for c in cloud_input.split(",") if c.strip()]
    else:
        keyword = raw_text
        cloud_list = []
    
    # 验证网盘有效性
    cloud_types = []
    invalid_clouds = []
    if cloud_list:
        for cloud in cloud_list:
            if cloud in CLOUD_TYPE_MAP:
                cloud_types.append(CLOUD_TYPE_MAP[cloud])
            else:
                invalid_clouds.append(cloud)
        if invalid_clouds:
            await pansou.finish(
                f"无效网盘：{', '.join(invalid_clouds)}\n"
                f"支持网盘：{SUPPORTED_CLOUDS}"
            )
    
    # 业务逻辑：调用接口（仅捕获业务异常，不捕获流程异常）
    try:
        # 构建请求数据
        request_data = {"kw": keyword}
        if cloud_types:
            request_data["cloud_types"] = cloud_types
        
        # 调用搜索接口（带超时控制）
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(request_data),
                timeout=30
            )
        
        # 状态码检查
        if response.status_code != 200:
            await pansou.finish(
                f"接口错误：状态码 {response.status_code}\n"
                f"内容：{response.text[:100]}..."
            )
        
        # JSON解析
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            await pansou.finish(f"接口返回非JSON数据：{response.text[:100]}...")
        
        # 业务状态检查
        if response_data.get("code") != 0:
            await pansou.finish(f"搜索失败：{response_data.get('message', '未知错误')}")
        
        # 处理无结果情况
        data = response_data.get("data", {})
        total = data.get("total", 0)
        merged_results = data.get("merged_by_type", {})
        if total == 0:
            msg = f"未找到「{keyword}」的资源"
            if cloud_list:
                msg += f"（网盘：{', '.join(cloud_list)}）"
            await pansou.finish(msg + "，换个关键词试试吧~")
        
        # 构建结果文本
        result_text = [
            f"【盘搜结果】共{total}个资源",
            f"关键词：{keyword}",
            f"网盘范围：{', '.join(cloud_list) if cloud_list else '全部支持网盘'}\n"
        ]
        
        # 按网盘类型整理结果
        for pan_type, items in merged_results.items():
            if items and pan_type in PAN_TYPE_MAPPING:
                result_text.append(f"=== {PAN_TYPE_MAPPING[pan_type]} ===")
                for idx, item in enumerate(items, 1):
                    note = item.get("note", "无描述")
                    url = item.get("url", "无链接")
                    password = item.get("password", "").strip()
                    
                    link_part = f"链接：{url}"
                    if password:
                        link_part += f" | 提取码：{password}"
                    
                    result_text.append(f"{idx}. {note}\n   {link_part}\n")
        
        # 强制发送合并转发
        full_text = "\n".join(result_text).strip()
        await send_force_forward_msg(bot, event, full_text)
    
    # 仅捕获业务异常（网络、接口等），流程异常让NoneBot自动处理
    except httpx.ConnectError:
        await pansou.finish(f"无法连接搜索服务器，请检查API地址：{API_URL}")
    except httpx.TimeoutException:
        await pansou.finish("搜索超时（超过30秒），请稍后再试")
    except Exception as e:
        await pansou.finish(f"搜索出错：{str(e)[:50]}...")


# ------------------------------ 状态查询处理 ------------------------------
@pansou_status.handle()
# 关键：同样注入Bot实例，避免依赖Matcher的bot属性
async def handle_pansou_status(bot: Bot, event: MessageEvent):
    try:
        # 调用健康检查接口
        async with httpx.AsyncClient() as client:
            response = await client.get(HEALTH_API_URL, timeout=10)
        
        if response.status_code != 200:
            await pansou_status.finish(
                f"状态接口错误：{response.status_code}\n"
                f"内容：{response.text[:100]}..."
            )
        
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            await pansou_status.finish(f"状态接口返回非JSON数据：{response.text[:100]}...")
        
        # 构建状态文本
        server_status = response_data.get("status", "未知")
        plugins_enabled = response_data.get("plugins_enabled", False)
        plugin_count = response_data.get("plugin_count", 0)
        
        status_text = [
            "【盘搜服务状态】",
            f"服务器运行：{'正常' if server_status == 'ok' else '异常'}",
            f"插件启用：{'是' if plugins_enabled else '否'}",
            f"已加载插件数：{plugin_count}个",
            f"接口地址：{HEALTH_API_URL}"
        ]
        
        # 状态查询也强制合并转发
        await send_force_forward_msg(bot, event, "\n".join(status_text))
    
    # 仅捕获业务异常
    except httpx.ConnectError:
        await pansou_status.finish(f"无法连接状态服务器：{HEALTH_API_URL}")
    except httpx.TimeoutException:
        await pansou_status.finish("状态查询超时（超过10秒）")
    except Exception as e:
        await pansou_status.finish(f"状态查询出错：{str(e)[:50]}...")