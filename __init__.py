from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
import httpx
import json

# ==================== 配置区域 ====================
API_URL = "http://xxx.xxx.xxx/api/search"  # 搜索接口地址
HEALTH_API_URL = "http://xxx.xxx.xxx/api/health"  # 健康检查接口地址
# ==================================================================

# 插件元数据
__plugin_meta__ = PluginMetadata(
    name="盘搜",
    description="NoneBot2 网盘资源搜索插件",
    usage="/盘搜 关键词\n或指定网盘：/盘搜 关键词 百度网盘,阿里云盘",
    type="application",
    homepage="https://github.com/rensumo/nonebot-plugin-pansou",
    supported_adapters={"~onebot.v11"},
)

# 网盘类型映射
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

# 结果显示用的网盘名称映射
PAN_TYPE_MAPPING = {v: k for k, v in CLOUD_TYPE_MAP.items()}

# 支持的网盘类型列表
SUPPORTED_CLOUDS = ", ".join(CLOUD_TYPE_MAP.keys())

# 创建命令处理器
pansou = on_command("pansou", aliases={"盘搜"}, priority=5, block=True)
pansou_status = on_command("pansou status", aliases={"盘搜 状态"}, priority=5, block=True)


def split_long_message(message: str, max_length: int = 500) -> list:
    """将长消息分割成多个部分，每部分不超过max_length个字符"""
    if len(message) <= max_length:
        return [message]
    
    parts = []
    current_part = ""
    
    # 按行分割，保持行的完整性
    lines = message.split('\n')
    for line in lines:
        # 如果当前行本身就超过最大长度，需要进一步分割
        if len(line) > max_length:
            if current_part:
                parts.append(current_part)
                current_part = ""
            
            # 按最大长度分割长行
            start = 0
            while start < len(line):
                end = start + max_length
                # 尽量在空格处分割，避免在文字中间分割
                if end < len(line) and line[end] != ' ':
                    last_space = line.rfind(' ', start, end)
                    if last_space != -1:
                        end = last_space + 1
                parts.append(line[start:end].strip())
                start = end
        else:
            # 如果加上当前行会超过最大长度，就保存当前部分并开始新的部分
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part)
                current_part = line
            else:
                if current_part:
                    current_part += '\n' + line
                else:
                    current_part = line
    
    if current_part:
        parts.append(current_part)
    
    return parts


async def send_long_message(bot, event: MessageEvent, message: str, max_length: int = 500):
    """发送长消息，超过指定长度时使用合并转发"""
    if len(message) <= max_length:
        await pansou.send(message)
        return
    
    # 分割消息
    message_parts = split_long_message(message, max_length)
    
    # 如果只有2部分，直接发送两条消息
    if len(message_parts) <= 2:
        for part in message_parts:
            await pansou.send(part)
        return
    
    # 超过2部分时使用合并转发
    try:
        # 构建转发消息节点
        forward_messages = []
        for i, part in enumerate(message_parts, 1):
            node = MessageSegment.node_custom(
                user_id=event.self_id,
                nickname="盘搜助手",
                content=Message(part)
            )
            forward_messages.append(node)
        
        # 发送合并转发消息
        await bot.send_forward_msg(
            user_id=event.user_id,
            messages=forward_messages
        )
        
    except Exception as e:
        # 如果合并转发失败，回退到普通消息分段发送
        await pansou.send("搜索结果较多，正在分段发送...")
        for i, part in enumerate(message_parts, 1):
            await pansou.send(f"【{i}/{len(message_parts)}】\n{part}")


@pansou.handle()
async def handle_pansou(event: MessageEvent, args: Message = CommandArg()):
    # 获取原始参数文本
    raw_text = args.extract_plain_text().strip()
    if not raw_text:
        await pansou.finish(
            f"请输入搜索关键词，格式：\n"
            f"/pansou 关键词 [指定网盘，用逗号分割，可选]\n"
            f"支持的网盘：{SUPPORTED_CLOUDS}"
        )
    
    # 解析关键词和指定的网盘类型
    parts = raw_text.rsplit(" ", 1)
    if len(parts) == 2:
        keyword, cloud_input = parts
        # 处理网盘输入
        cloud_list = [c.strip() for c in cloud_input.split(",") if c.strip()]
    else:
        keyword = raw_text
        cloud_list = []
    
    # 验证并转换网盘类型
    cloud_types = []
    invalid_clouds = []
    if cloud_list:
        for cloud in cloud_list:
            if cloud in CLOUD_TYPE_MAP:
                cloud_types.append(CLOUD_TYPE_MAP[cloud])
            else:
                invalid_clouds.append(cloud)
        
        # 检查无效网盘类型
        if invalid_clouds:
            await pansou.finish(
                f"发现无效的网盘类型：{', '.join(invalid_clouds)}\n"
                f"支持的网盘：{SUPPORTED_CLOUDS}"
            )
    
    try:
        # 构建请求数据
        request_data = {"kw": keyword}
        if cloud_types:
            request_data["cloud_types"] = cloud_types
        
        # 发送搜索请求
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    API_URL,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(request_data),
                    timeout=30  # 设置30秒超时
                )
            except httpx.ConnectError:
                await pansou.finish(f"无法连接到搜索服务器，请检查API地址是否正确：\n{API_URL}")
            except httpx.TimeoutException:
                await pansou.finish("搜索请求超时，请稍后再试")
        
        # 检查HTTP状态码
        if response.status_code != 200:
            await pansou.finish(
                f"搜索接口返回错误状态码：{response.status_code}\n"
                f"响应内容：{response.text[:200]}..."  # 显示前200字符
            )
        
        # 解析JSON响应
        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            await pansou.finish(
                f"搜索接口返回内容不是有效的JSON格式\n"
                f"错误详情：{str(e)}\n"
                f"响应内容：{response.text[:200]}..."
            )
        
        # 检查API业务状态码
        if response_data.get("code") != 0:
            await pansou.finish(f"搜索失败：{response_data.get('message', '未知错误')}")
        
        # 提取搜索结果
        data = response_data.get("data", {})
        total = data.get("total", 0)
        merged_results = data.get("merged_by_type", {})
        
        if total == 0:
            msg = f"未搜索到关于 {keyword} 的结果"
            if cloud_types:
                msg += f"（指定网盘：{', '.join(cloud_list)}）"
            msg += " 喵~"
            await pansou.finish(msg)
        
        # 构建搜索结果文本
        result_text = [f"共搜索到{total}个结果"]
        if cloud_types:
            result_text.append(f"以下是关于 {keyword} 在{', '.join(cloud_list)}中的搜索结果 喵~")
        else:
            result_text.append(f"以下是关于 {keyword} 的搜索结果 喵~")
        
        # 按类型添加结果
        for pan_type, items in merged_results.items():
            if items and pan_type in PAN_TYPE_MAPPING:
                result_text.append(f"\n{PAN_TYPE_MAPPING[pan_type]}：")
                for item in items:
                    note = item.get("note", "无描述")
                    url = item.get("url", "无链接")
                    password = item.get("password", "").strip()  # 去除首尾空格
                    
                    # 构建链接部分
                    link_part = f"提取链接：{url}"
                    if password:  # 只有提取码非空时才添加
                        link_part += f" 提取码：{password}"
                    
                    result_text.append(f"{note}\n{link_part}")
        
        # 合并结果文本并使用长消息发送
        full_text = "\n".join(result_text)
        bot = pansou.bot
        await send_long_message(bot, event, full_text)
            
    except Exception as e:
        await pansou.finish(f"搜索过程出错：{str(e)}")


@pansou_status.handle()
async def handle_pansou_status(event: MessageEvent):
    try:
        # 发送健康检查请求
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(HEALTH_API_URL, timeout=10)
            except httpx.ConnectError:
                await pansou_status.finish(f"无法连接到状态服务器，请检查地址是否正确：\n{HEALTH_API_URL}")
            except httpx.TimeoutException:
                await pansou_status.finish("状态查询超时，请稍后再试")
        
        # 检查HTTP状态码
        if response.status_code != 200:
            await pansou_status.finish(
                f"状态接口返回错误状态码：{response.status_code}\n"
                f"响应内容：{response.text[:200]}..."
            )
        
        # 解析JSON响应
        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            await pansou_status.finish(
                f"状态接口返回内容不是有效的JSON格式\n"
                f"错误详情：{str(e)}\n"
                f"响应内容：{response.text[:200]}..."
            )
        
        # 解析状态信息
        server_status = response_data.get("status", "")
        plugins_enabled = response_data.get("plugins_enabled", False)
        plugin_count = response_data.get("plugin_count", 0)
        
        # 构建状态文本
        status_text = []
        status_text.append("服务器运行正常 喵~" if server_status == "ok" else "服务器运行不正常呢 喵~")
        status_text.append("插件已启用" if plugins_enabled else "插件已禁用")
        status_text.append(f"已加载{plugin_count}个插件")
        
        await pansou_status.send("\n".join(status_text))
        
    except Exception as e:
        await pansou_status.finish(f"查询状态出错：{str(e)}")