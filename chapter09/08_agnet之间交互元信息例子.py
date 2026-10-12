# 9 Agent间通信协议格式
# 以Qwen3.0智能体系统中应用的标准通信格式为例，一条完整的Agent通信消息如下所示（结构化抽象）：
{
  "id": "msg-20240503-00123",
  "timestamp": "2025-05-03T13:45:27Z",
  "from": "agent:task_dispatcher",
  "to": "agent:data_parser",
  "type": "command",
  "priority": 2,
  "context_ref": ["mem-1001", "task-req-879"],
  "payload": {
    "function": "parse_table",
    "args": {
      "file_url": "https://data.gov.cn/table.csv",
      "columns": ["region", "gdp"]
    }
  },
  "auth": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "signature": "b1a927ec3..."
  }
}