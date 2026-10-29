"""Safe, actionable guidance for text providers; never inspect upstream text."""


def classify_failure(code, *, http_status=None, stop_reason=None, cause=None):
    """Return a fixed category and optional replacement for a domain's message."""
    if type(code) is not str:
        code = None
    if stop_reason == "task_authority_changed":
        return "task_changed", "任务权限、模型配置或执行租约已改变，已停止后续调用；请刷新任务并核对当前配置"
    if code == "PROVIDER_CONFIGURATION":
        return "configuration", "模型服务配置不可用，请管理员检查服务地址、模型名称和凭据"
    if stop_reason != "deadline" and cause == "connection_failure":
        return "connection", "无法连接模型服务，请管理员检查服务进程、网络和接口地址"
    if stop_reason == "deadline" or code == "PROVIDER_TIMEOUT" or (isinstance(code, str) and code.endswith("_PROVIDER_TIMEOUT")):
        return "timeout", "模型调用超过本次总时限；请先查看任务记录和服务端执行情况，再决定是否重新生成"
    if cause == "delivery_unknown":
        return "delivery_unknown", "模型请求发送或响应接收中断；请先查看任务记录和服务端执行情况，确认后再重新生成"
    # Apply HTTP guidance only to failed HTTP exchanges, never to a completed
    # response whose domain-specific validation rejected the content.
    if type(http_status) is int and 300 <= http_status <= 599:
        if http_status == 401:
            return "authentication", "模型服务认证失败，请管理员更新密钥并检查凭据配置"
        if http_status == 403:
            return "access_denied", "模型服务拒绝访问，请管理员检查账号的模型权限和服务访问策略"
        if http_status == 404:
            return "endpoint", "模型服务地址或模型不存在，请管理员核对接口路径和模型名称"
        if http_status == 402:
            return "quota", "模型服务额度不足，请管理员检查余额、账单和用量配额"
        if http_status == 413:
            return "request_too_large", "模型请求超过服务容量，请管理员调整输入范围或模型请求上限"
        if http_status in {400, 422}:
            return "request_invalid", "模型服务不接受当前请求，请管理员检查模型参数和接口格式"
        if http_status == 429:
            if stop_reason == "retry_after_limit":
                return "rate_limit", "模型服务限流，要求等待较长时间；请按服务端限流策略稍后再生成"
            return "rate_limit", "模型服务限流，请稍后手动重新生成；管理员可检查并发量和配额"
        if http_status in {502, 503, 504}:
            return "temporary_unavailable", "模型服务暂时不可用，请稍后手动重新生成"
        if 300 <= http_status < 400:
            return "redirect", "模型接口返回重定向，请管理员配置可直接访问的接口地址"
        if http_status >= 500:
            return "upstream_error", "模型服务内部错误，请管理员检查服务运行状态和对应请求日志"
        return "http_error", "模型服务拒绝了本次请求，请管理员核对服务配置和请求日志"
    if cause == "connection_failure" or code == "PROVIDER_UNAVAILABLE":
        return "connection", "无法连接模型服务，请管理员检查服务进程、网络和接口地址"
    if code in {"INVALID_PROVIDER_RESPONSE", "INVALID_OUTPUT"}:
        return "invalid_response", "模型返回格式不符合要求，请管理员检查模型是否支持结构化输出及当前 Prompt"
    if code in {"INVALID_CITATION", "UNGROUNDED_OUTPUT"}:
        return "invalid_evidence", "模型结果的来源引用未通过核对，请管理员检查可用知识来源和当前 Prompt"
    if code == "RESPONSE_TOO_LARGE":
        return "response_too_large", "模型响应超过系统接收上限，请管理员检查输出长度和响应格式"
    if code == "INCOMPLETE_RESPONSE":
        return "incomplete_response", "模型响应未完成，请管理员检查输出长度上限和模型结束原因"
    if code == "MODEL_REFUSAL":
        return "refusal", "模型拒绝了本次请求，请核对输入内容和模型使用策略"
    # Native protocols already have precise source/receipt validation messages.
    return "domain_error", None
