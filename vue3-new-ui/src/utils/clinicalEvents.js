import { baseURL, tokenName } from "@/config";
import eventBus from "@/utils/eventBus";
import { ElNotification } from "element-plus";

const EVENT_MESSAGES = {
  "queue.called": (event) => `请 ${event.data.queue_number} 号患者就诊`,
  "lab.critical": () => "发现新的检验危急值，请立即处理",
  "lab.result_available": () => "检验结果已审核发布",
  "lab.result_received": () => "LIS 已同步新的检验结果",
  "imaging.report_received": () => "PACS 已同步新的影像报告",
  "payment.succeeded": () => "支付已成功到账",
  "payment.failed": () => "支付失败，请核对原因",
  "prescription.created": () => "收到新的待审核处方",
};

class ClinicalEventStream {
  constructor() {
    this.controller = null;
    this.retryTimer = null;
    this.retryCount = 0;
    this.lastEventId = "";
    this.token = "";
  }

  start(token) {
    if (!token || token === this.token) return;
    this.stop();
    this.token = token;
    this.connect();
  }

  stop() {
    this.controller?.abort();
    clearTimeout(this.retryTimer);
    this.controller = null;
    this.retryTimer = null;
    this.retryCount = 0;
    this.token = "";
  }

  async connect() {
    const token = this.token;
    if (!token) return;
    this.controller = new AbortController();
    try {
      const headers = { Accept: "text/event-stream", [tokenName]: token };
      if (this.lastEventId) headers["Last-Event-ID"] = this.lastEventId;
      const response = await fetch(`${baseURL}/events/stream`, {
        headers,
        cache: "no-store",
        signal: this.controller.signal,
      });
      if (response.status === 401 || response.status === 403) {
        this.stop();
        return;
      }
      if (!response.ok || !response.body) throw new Error(`event stream HTTP ${response.status}`);
      this.retryCount = 0;
      await this.consume(response.body.getReader());
      if (this.token === token) this.scheduleReconnect();
    } catch (error) {
      if (error?.name !== "AbortError" && this.token === token) this.scheduleReconnect();
    }
  }

  async consume(reader) {
    const decoder = new TextDecoder();
    let buffer = "";
    while (this.token) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        this.handleBlock(block);
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  handleBlock(block) {
    if (!block || block.startsWith(":")) return;
    const fields = {};
    for (const line of block.split("\n")) {
      const separator = line.indexOf(":");
      if (separator > 0) fields[line.slice(0, separator)] = line.slice(separator + 1).trimStart();
    }
    if (!fields.data) return;
    try {
      const event = JSON.parse(fields.data);
      this.lastEventId = fields.id || event.id || this.lastEventId;
      eventBus.emit("clinical-event", event);
      const message = EVENT_MESSAGES[event.type];
      if (message) {
        ElNotification({
          title: event.type === "lab.critical" ? "紧急提醒" : "业务动态",
          message: message(event),
          type: event.type === "lab.critical" || event.type === "payment.failed" ? "warning" : "info",
          duration: event.type === "lab.critical" ? 0 : 5000,
        });
      }
    } catch (error) {
      console.warn("无法解析临床事件", error);
    }
  }

  scheduleReconnect() {
    if (!this.token || this.retryTimer) return;
    const delay = Math.min(30000, 1000 * 2 ** this.retryCount) + Math.floor(Math.random() * 500);
    this.retryCount += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }
}

export const clinicalEventStream = new ClinicalEventStream();
