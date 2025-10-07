from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import MessageEvent, Message, MessageSegment, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.exception import FinishedException  # 导入FinishedException（仅用于显式说明，不捕获）
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
    description="NoneBot2 网盘资源搜索插件",
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
    """强制合并转发函数（不捕获FinishedException，仅处理发送本身异常）"""
    message_parts = split_long_message(message)
    
    # 构建合并转发节点
    forward_nodes = [
        MessageSegment.node_custom(
            user_id=event.self_id,
            nickname="盘搜助手",
            content=Message(part)
        ) for part in message_parts
    ]
    
    # 根据事件类型选择发送方式（仅捕获发送相关异常，不吞FinishedException）
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.send_forward_msg(
                group_id=event.group_id,
                messages=forward_nodes
            )
        else:
            await bot.send_forward_msg(
                user_id=event.user_id,
                messages=forward_nodes
            )
    except Exception as e:
        # 仅处理合并转发失败的回退逻辑，不捕获FinishedException
        error_msg = f"合并转发暂不可用（{str(e)[:20]}），分段发送："
        if isinstance(event, GroupMessageEvent):
            await bot.send_group_msg(group_id=event.group_id, message=error_msg)
        else:
            await bot.send_private_msg(user_id=event.user_id, message=error_msg)
        
        for i, part in enumerate(message_parts, 1):
            part_msg = f"【{i}/{len(message_parts)}】\n{part}"
            if isinstance(event, GroupMessageEvent):
                await bot.send_group_msg(group_id=event.group_id, message=part_msg)
            else:
                await bot.send_private_msg(user_id=event.user_id, message=part_msg)


# ------------------------------ 搜索命令处理 ------------------------------
@pansou.handle()
async def handle_pansou(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    raw_text = args.extract_plain_text().strip()
    
    # 格式错误直接终止（触发FinishedException，不捕获）
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
    
    # 验证网盘有效性（无效直接终止）
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
    
    # 业务逻辑：调用接口（仅捕获业务异常，不吞FinishedException）
    try:
        # 构建请求数据
        request_data = {"kw": keyword}
        if cloud_types:
            request_data["cloud_types"] = cloud_types
        
        # 调用搜索接口
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={"Content-Type": "application/json"},
                data=json.dumps(request_data),
                timeout=30
            )
        
        if response.status_code != 200:
            await pansou.finish(
                f"接口错误：状态码 {response.status_code}\n"
                f"内容：{response.text[:100]}..."
            )
        
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            await pansou.finish(f"接口返回非JSON数据：{response.text[:100]}...")
        
        if response_data.get("code") != 0:
            await pansou.finish(f"搜索失败：{response_data.get('message', '未知错误')}")
        
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
        
        # 发送合并转发（不捕获FinishedException，异常直接抛出）
        full_text = "\n".join(result_text).strip()
        await send_force_forward_msg(bot, event, full_text)
    
    except httpx.ConnectError:
        await pansou.finish(f"无法连接搜索服务器，请检查API地址：{API_URL}")
    except httpx.TimeoutException:
        await pansou.finish("搜索超时（超过30秒），请稍后再试")
    # 不捕获FinishedException，让其正常终止命令流程
    except Exception as e:
        await pansou.finish(f"搜索出错：{str(e)[:50]}...")


# ------------------------------ 状态查询处理 ------------------------------
@pansou_status.handle()
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
        
        # 发送合并转发（不捕获FinishedException）
        await send_force_forward_msg(bot, event, "\n".join(status_text))
    
    except httpx.ConnectError:
        await pansou_status.finish(f"无法连接状态服务器：{HEALTH_API_URL}")
    except httpx.TimeoutException:
        await pansou_status.finish("状态查询超时（超过10秒）")
    # 不捕获FinishedException，保留原生终止逻辑
    except Exception as e:
        await pansou_status.finish(f"状态查询出错：{str(e)[:50]}...")
