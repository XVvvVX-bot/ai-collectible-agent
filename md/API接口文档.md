# 赵涌 · 搜索服务 API 接口文档

本文档面向**外部接入方**，说明如何调用搜索与拍品相关接口，包括鉴权方式、请求头、参数及返回格式。

---

## 一、概述

| 项目 | 说明 |
|------|------|
| 服务名称 | 搜索与拍品服务（bidding-search） |
| 协议 | HTTP/HTTPS |
| 数据格式 | 请求：Query 参数；响应：JSON |
| 字符编码 | UTF-8 |

**基础地址**（以实际部署为准，示例）：

- 生产环境：`http://8.218.2.12:8888`

---

## 二、鉴权说明

所有以 `/api/` 开头的接口均需要鉴权，请在**每次请求**的 HTTP Header 中携带以下两个头。

### 2.1 请求头

| Header 名称 | 类型 | 必填 | 说明 |
|-------------|------|------|------|
| `X-Auth-Timestamp` | 字符串（数字） | 是 | 当前时间的毫秒时间戳，用于防重放与过期校验 |
| `X-Auth-Token` | 字符串 | 是 | 根据**加密算法**计算得到的签名字符串 |

### 2.2 加密算法

- **算法**：MD5（32 位小写十六进制）
- **输入**：`secret + timestamp`（字符串拼接，无分隔符）
  - `secret`：由**服务提供方**分配并线下告知的密钥
  - `timestamp`：与请求头 `X-Auth-Timestamp` **完全一致**的字符串（毫秒时间戳）
- **输出**：将上述拼接串做 MD5 后的十六进制字符串，作为 `X-Auth-Token` 的值（大小写不敏感，服务端按忽略大小写比对）

**公式**：

```
X-Auth-Token = MD5( secret + X-Auth-Timestamp )
```

- 编码：参与 MD5 计算的字符串按 **UTF-8** 编码。
- 时间有效期：服务端会校验 `X-Auth-Timestamp` 与服务器时间的偏差，超过约 **5 分钟**（300 秒）的请求将视为“请求已过期”并返回 401。请保证客户端时间与标准时间同步。

### 2.3 密钥（secret）

- **含义**：用于计算 `X-Auth-Token` 的密钥。
- **获取方式**：由**赵涌服务提供方**线下分配，不通过接口返回。
- **安全要求**：请妥善保管，勿写入前端代码或公开仓库；仅在后端或受控环境中计算 Token。

---

## 三、Token 计算示例

假设：

- 密钥：`zhao123`（仅为示例，实际以服务方分配为准）
- 当前时间毫秒时间戳：`1730707200000`

则：

1. 拼接串：`zhao123` + `1730707200000` → `zhao1231730707200000`
2. 对 `zhao1231730707200000` 做 UTF-8 编码后计算 MD5，得到 32 位十六进制字符串。
3. 将该字符串作为请求头 `X-Auth-Token` 的值。

**Java 示例**：

```java
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

public class TokenUtil {

    public static String md5(String input) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5");
        byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte b : digest) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }

    public static void main(String[] args) throws Exception {
        String secret = "zhao123";  // 替换为实际分配的密钥
        String timestamp = String.valueOf(System.currentTimeMillis());
        String token = md5(secret + timestamp);
        System.out.println("X-Auth-Timestamp: " + timestamp);
        System.out.println("X-Auth-Token: " + token);
    }
}
```

**JavaScript（Node）示例**：

```javascript
const crypto = require('crypto');

function getAuthHeaders(secret) {
  const timestamp = String(Date.now());
  const signStr = secret + timestamp;
  const token = crypto.createHash('md5').update(signStr, 'utf8').digest('hex');
  return {
    'X-Auth-Timestamp': timestamp,
    'X-Auth-Token': token,
  };
}

const secret = 'zhao123';  
const headers = getAuthHeaders(secret);
console.log(headers);
```

**Python 示例**：

```python
import hashlib
import time

def get_auth_headers(secret: str):
    timestamp = str(int(time.time() * 1000))
    sign_str = secret + timestamp
    token = hashlib.md5(sign_str.encode('utf-8')).hexdigest()
    return {
        'X-Auth-Timestamp': timestamp,
        'X-Auth-Token': token,
    }

secret = 'zhao123'  # 替换为实际分配的密钥
headers = get_auth_headers(secret)
print(headers)
```

---

## 四、接口列表

### 4.1 搜索接口（第三方搜索代理）

根据拍品状态与分页参数，返回拍品列表（数据来源为第三方搜索服务，已转换为统一结构）。

**请求**

| 项目 | 说明 |
|------|------|
| 方法 | `GET` |
| 路径 | `/api/search` |

**Query 参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明                  |
|--------|------|------|--------|---------------------|
| status | int | 是 | - | 拍品状态：`1` 预展，`2` 竞买中 |
| page | int | 否 | 1 | 页码，从 1 开始           |
| pageSize | int | 否 | 50 | 每页条数,最高不能超过50       |

**响应**

- 成功：HTTP 200，Body 为分页结果，结构见下文「五、统一分页与拍品结构」。
- 鉴权失败：HTTP 401，Body 中为错误信息。
- 请求过于频繁：HTTP 429（限流）。

---

## 五、统一分页与拍品结构

两个接口（搜索、数据库拍品列表）均采用同一分页结构与拍品字段，便于前端统一处理。

### 5.1 分页包装（PageInfo）

```json
{
  "total": 100,
  "list": [ { /* 拍品对象 */ } ],
  "pageNum": 1,
  "pageSize": 50,
  "size": 50,
  "pages": 2,
  "isFirstPage": true,
  "isLastPage": false,
  "hasPreviousPage": false,
  "hasNextPage": true,
  "navigatePages": 8,
  "navigatepageNums": [1, 2],
  "prePage": 0,
  "nextPage": 2
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| total | long | 总记录数 |
| list | array | 当前页的拍品列表 |
| pageNum | int | 当前页码 |
| pageSize | int | 每页条数 |
| pages | int | 总页数 |

### 5.2 拍品对象（Auctions）

列表中每项为拍品对象，字段可能为空（未返回或无数据时）。时间字段为 ISO 8601 或时间戳格式（由服务端统一）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 ID |
| auctionNo | string | 拍品编号 |
| name | string | 拍品名称 |
| contractId | int | 合同 ID |
| status | string | 拍品状态：0 全部；1 预展；2 竞拍中；3 成交 |
| auctionType | string | 拍品类型：1 竞拍，0 一口价 |
| auctionCategoryId | long | 分类 ID |
| auctionCharacterId | long | 品级 ID |
| descr | string | 拍品描述 |
| descrCharacter | string | 品级描述 |
| picPath | string | 列表默认图片地址 |
| startAt | string/date | 开拍时间 |
| endAt | string/date | 结束时间 |
| previewAt | string/date | 预展开始时间 |
| ratingAgency | string | 评级机构 |
| ratingScore | string | 评级分数 |
| initialPrice | double | 起拍价 |
| endPrice | double | 成交价 |
| videoUrl | string | 视频地址 |
| auctionSpecialTopicId | long | 高分评级专场 ID |
| isDelay | int | 是否延时拍：0 否，1 是 |
| delayTime | int | 延时拍时间（秒） |
| settlementStatus | int | 结算状态 |

---

## 六、请求示例

### 6.1 cURL

```bash
# 1. 生成当前时间戳和 Token（此处需在本地用上述算法计算）
TIMESTAMP=$(date +%s)000
# 若使用固定示例（仅测试）：TIMESTAMP=1730707200000
SECRET="zhao123"
TOKEN=$(echo -n "${SECRET}${TIMESTAMP}" | md5sum | cut -d' ' -f1)

# 2. 调用搜索接口
curl -X GET "http://8.218.2.12:8888/api/search?status=2&page=1&pageSize=10" \
  -H "X-Auth-Timestamp: ${TIMESTAMP}" \
  -H "X-Auth-Token: ${TOKEN}" \
  -H "Content-Type: application/json"
```

### 6.2 示例响应（片段）

```json
{
  "total": 11303,
  "pageNum": 1,
  "pageSize": 10,
  "list": [
    {
      "id": 3856651,
      "auctionNo": "216235009",
      "name": "纪50",
      "contractId": null,
      "status": "2",
      "auctionType": "1",
      "auctionCategoryId": 173,
      "auctionCharacterId": 2,
      "descr": null,
      "descrCharacter": null,
      "picPath": "https://img3.zhaoonline.com/2021/41/489305003A.jpg",
      "startAt": 1734941998000,
      "endAt": 1798020240000,
      "previewAt": null,
      "ratingAgency": null,
      "ratingScore": null,
      "initialPrice": 1.0,
      "endPrice": null,
      "videoUrl": null,
      "auctionSpecialTopicId": 0,
      "isDelay": 0,
      "delayTime": null,
      "settlementStatus": null,
      "images": [
        {
          "width": 2077,
          "url": "https://img3.zhaoonline.com/2021/41/489305003A.jpg",
          "height": 1506
        }
      ]
    }
  ]
}
```

---

## 七、错误说明

| HTTP 状态码 | 说明 | 处理建议 |
|-------------|------|----------|
| 401 | 缺少认证信息 / 时间戳格式错误 / 请求已过期 / Token 校验失败 | 检查是否携带 `X-Auth-Timestamp`、`X-Auth-Token`，时间是否在允许偏差内，密钥与算法是否正确 |
| 429 | 请求过于频繁 | 降低调用频率，稍后重试 |
| 500 | 服务端异常 | 联系服务提供方或稍后重试 |

鉴权失败时，响应 Body 中会包含具体错误信息（如「缺少认证信息」「Token 校验失败」等），便于排查。

---

## 八、附录：鉴权与密钥汇总

| 项目 | 内容 |
|------|------|
| 请求头 1 | `X-Auth-Timestamp`：当前毫秒时间戳（字符串） |
| 请求头 2 | `X-Auth-Token`：MD5( secret + X-Auth-Timestamp )，32 位十六进制 |
| 编码 | UTF-8 |
| 时间有效范围 | 约 ±5 分钟（以服务端配置为准） |
| 密钥（secret） | 由服务提供方线下分配，不通过接口返回 |

如有接入或环境问题，请联系赵涌技术对接人获取**正式环境地址**及**分配给您的密钥**。
