# Cuckoo 电商图片翻译系统

[English](README.md)

Cuckoo 是一个面向跨境电商商品图的本地优先图片翻译系统。它可以识别商品图片中的中文文字，将文字翻译成英文，擦除原始中文区域，并在原图分辨率基础上写回英文内容，生成高清英文版商品图。

当前版本适合课程项目演示和本地开发：

- 后端使用 FastAPI，提供批量上传、任务进度查询和结果下载接口。
- 前端为后端直接托管的上传工作台，无需单独构建前端项目。
- OCR 使用 PaddleOCR，相关封装参考了短剧出海项目中的 OCR 模块思路。
- 翻译支持 mock、本地演示、OpenAI-compatible/Qwen-MT 接口和 DeepL 接口。
- 图像处理使用 OpenCV 和 Pillow，对原中文区域进行修复并重新排版英文。
- 默认使用本地 `data/` 存储上传图和输出图，后续可扩展到 S3、GCS 等云存储。

## 功能特性

- 批量上传：支持一次上传 1-30 张商品图。
- 中文识别：只处理 OCR 结果中包含中文的文本区域。
- 自动翻译：支持中文到英文，后续可扩展更多语言。
- 高清输出：输出图像保持原图分辨率。
- 结果预览：网页端展示每张图片的识别区域数和替换区域数。
- 打包下载：任务完成后可下载全部生成图片的 ZIP 压缩包。

## 快速启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

启动后打开：

```text
http://127.0.0.1:8000
```

健康检查接口：

```text
http://127.0.0.1:8000/health
```

## 翻译配置

默认配置为：

```env
TRANSLATOR_PROVIDER=mock
```

mock 模式用于本地演示，不需要 API Key。它会优先匹配少量内置电商词汇，例如“三合一电磁辐射检测仪”，没有匹配时会返回带目标语言标记的文本。

### OpenAI-compatible / Qwen-MT

如果使用 302.ai Qwen-MT 或其他 OpenAI-compatible 翻译接口，在 `.env` 中配置：

```env
TRANSLATOR_PROVIDER=openai
TRANSLATE_ENDPOINT=https://example.com/v1/chat/completions
TRANSLATE_API_KEY=your-key
TRANSLATE_MODEL=qwen-mt-plus
```

### DeepL

如果使用 DeepL，在 `.env` 中配置：

```env
TRANSLATOR_PROVIDER=deepl
DEEPL_API_KEY=your-key
DEEPL_API_URL=https://api-free.deepl.com/v2/translate
```

## OCR 配置

默认 OCR 引擎为 PaddleOCR：

```env
OCR_ENGINE=paddle
OCR_LANG=ch
OCR_MIN_CONFIDENCE=0.55
PADDLE_TEXT_DETECTION_MODEL=PP-OCRv5_mobile_det
PADDLE_TEXT_RECOGNITION_MODEL=PP-OCRv5_mobile_rec
```

首次真实处理图片时，PaddleOCR 可能需要加载或下载模型，因此第一次运行会比后续更慢。

## API 接口

### 创建图片翻译任务

```http
POST /api/jobs
```

表单字段：

- `files`: 图片文件列表，支持 1-30 张。
- `source_language`: 源语言，默认 `zh`。
- `target_language`: 目标语言，默认 `en`。

### 查询任务进度

```http
GET /api/jobs/{job_id}
```

返回任务状态、进度、每张图片的输出地址、识别区域数和替换区域数。

### 下载任务结果

```http
GET /api/jobs/{job_id}/download
```

任务完成后返回 ZIP 文件。

### 健康检查

```http
GET /health
```

## 项目结构

```text
app/
  main.py            FastAPI 入口和 HTTP API
  ocr.py             PaddleOCR 图片文字识别
  translation.py     翻译提供方封装和重试缓存
  pipeline.py        图片翻译主流程
  image_renderer.py  文字擦除和英文回写
  jobs.py            本地内存任务状态
  storage.py         上传、输出和 ZIP 存储
static/
  index.html         上传工作台页面
  styles.css         页面样式
  app.js             前端交互逻辑
tests/
  test_pipeline.py   图片处理流程测试
  test_text_utils.py 文本过滤和清洗测试
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

当前测试覆盖：

- OCR 文本清洗。
- 只替换中文区域，保留非中文文本。
- 输出图片保持原始分辨率。
- 翻译结果被写入图片处理流水线。

## 后续扩展方向

- 将内存任务状态替换为 Celery/RQ + Redis/PostgreSQL。
- 将本地文件存储替换为 AWS S3、Google Cloud Storage 或其他对象存储。
- 增加用户登录、任务历史和权限控制。
- 增加人工校对页面，允许用户修正 OCR 结果和翻译结果后再生成图片。
- 增加更多语言对和商品类目术语词库。

## 上传 GitHub 前建议

- 不要提交 `.env`、`data/`、模型缓存和本地输出文件。
- 提交 `.env.example`，方便其他人按模板配置。
- 如果仓库用于课程展示，可以在 README 中放一张演示截图和一组示例输入/输出图。
