# 22/33 kV Automatic Pole Placement System

ระบบออกแบบและวางเสาไฟฟ้าเหนือดิน **22 kV / 33 kV** ตัวนำ **SAC 50 sq.mm.** ตามหลักศึกษา
มาตรฐานการไฟฟ้าและพลังงาน มี 2 หน้ากางที่ใช้ **เอนจินกลางตัวเดียวกัน** จึงได้ผลลัพธ์ตรงกันเสมอ

| หน้ากาง | ไฟล์ | วิธีใช้ |
|--------|------|--------|
| **เว็บสาธิต (GitHub Pages)** | `docs/` | เปิดลิงค์แล้วใช้ได้เลย ไม่ต้องติดตั้ง — เอนจิน Python รันในเบราว์เซอร์ผ่าน Pyodide |
| Web App (Flask + Canvas) | `app.py` | ลากวางเส้นทางบนผืนผ้าใบ ดูผล/ตรวจสอบ/ส่งออก CSV-PNG |
| CLI (matplotlib) | `pole_designer.py` | งาน batch บนเครื่อง ไม่ต้องเปิดเบราว์เซอร์ |

**ลองใช้ทันที:** https://icem79ai-ops.github.io/pole-line-designer/

แกนการคำนวณทั้งหมดอยู่ที่ `line_engine.py` (ไม่มี logic ซ้ำซ้อนระหว่าง CLI, เว็บ และเว็บสาธิต)

---

## 1. ติดตั้ง

```bash
python -m pip install -r requirements.txt
```

ต้องการ Python 3.11 ขึ้นไป (ทดสอบแล้วบน Python 3.14.3)

---

## 2. เปิดเว็บแอป

```bash
python app.py                    # เปิดที่ http://127.0.0.1:5000 และเปิดเบราว์เซอร์ให้
python app.py --no-browser       # ไม่เปิดเบราว์เซอร์อัตโนมัติ
python app.py --host 0.0.0.0 --port 5123    # ให้เครื่องอื่นใน LAN เข้าใช้
```

> ระบบไม่ต้องต่ออินเทอร์เน็ต ทุกอย่างคำนวณในเครื่อง จึงใช้งานในพื้นที่กระแสไฟฟ้าที่ไม่มีเน็ตได้

### สิ่งที่ทำได้บนหน้าเว็บ

- คลิกวาง centerline ทีละจุด (บอกระยะเป็นเมตร) หรือกด **โหลดตัวอย่าง** เพื่อทดลองทันที
- ปรับค่า R.O.W. offset (0–50 m), ความกว้างเขตทางจริง (0–50 m), ใช้/ไม่ใช้ break pole
- ระบบถอยแนวเสาออกอัตโนมัติเมื่อ offset ที่ขอมาน้อยกว่าความกว้างถนนครึ่งหนึ่ง + 2 m
- แสดงผังบน Canvas: ถนน, เขต R.O.W., centerline, เสาแต่ละต้นพร้อมป้าย
  สีตามชนิด (Start/End, Tangent, Curve, BA/SA/MA/LA, Break), ลูกศรสายยึดโยงชี้ตามแรงดึงจริง
- เลื่อนซูม/ลากเลื่อนภาพ, คลิกเสาเพื่อดูรายละเอียด, ล้าง, เลิกทำ, กรองตามชนิดเสา
- ตารางเสาพร้อมช่องค้นหา/กรองตามรหัสเสา, ผลตรวจสอบ 7 เกณฑ์พร้อมสถานะ, สรุปตัวเลขสำคัญ
- ตารางมาตรฐาน span อ้างอิง
- **ภาพพื้นหลังแผนที่ดาวเทียม (ไม่บังคับ)**: วางภาพที่ครอบตัดมาจาก Google Maps ได้ 3 ทาง
  (เลือกไฟล์ / Ctrl+V / ลากวาง) → **วัดระยะอ้างอิง** (คลิก 2 จุดบนจุดที่รู้ระยะจริง แล้วกรอกเมตร)
  ระบบจะปรับอัตราส่วนภาพให้ตรง → โหมด **ปรับภาพ** ลากเลื่อน / ล้อเมาส์ยืดหด / ปรับความโปร่งแสง
  → กด **ใช้ภาพนี้** แล้วปักแนวถนนตามถนนจริงได้เลย (PNG export จะติดภาพไปด้วย)
  - ภาพ**ไม่ถูกบันทึกลง localStorage** — เซฟเฉพาะเส้น/ผลออกแบบ, reload แล้วต้องวางภาพใหม่
  - ภาพถูกย่อเหลือไม่เกิน 2048 px ฝั่งยาว และไม่มีการครอบตัดในโปรแกรม (ครอบด้วย Paint/Snipping ก่อนวาง)
- ส่งออก **CSV**, **JSON**, **PNG** (ภาพหน้าจอ) และรายงานผล
- บันทึกงานล่าสุดในเบราว์เซอร์ (localStorage) และเปิดกลับมาได้ภายหลัง

### เว็บสาธิต (GitHub Pages) — ไม่ต้องติดตั้งอะไร

หน้าเว็บเดียวกันนี้ถูก build เป็นไฟล์ static ไว้ใน `docs/` แล้วเสิร์ฟผ่าน GitHub Pages
โดยเปลี่ยนจาก Flask เป็น **Pyodide** (`web/static/js/pyodide-bridge.js`):
หน้าเว็บโหลด `line_engine.py` ไปรันในเบราว์เซอร์และตอบ `/api/*` เอง

```bash
python -X utf8 build_static.py    # build หน้า static ลง docs/ (ใช้ตอนจะ publish)
python -X utf8 check_static.py    # ทดสอบ E2E ด้วยเบราว์เซอร์จริง (Pyodide boot + ผลเทียบเอนจิน)
```

- ผลลัพธ์ของ bridge เทียบกับ `line_engine` บนเครื่องแบบทศนิยมเดียวกัน (parity)
- ค่า CDN ครั้งแรก (~10 MB) ครั้งต่อไปเร็วขึ้นจาก browser cache
- โหมด Flask ปกติไม่ได้โหลด bridge นี้ จึงไม่กระทบการใช้งานเซิร์ฟเวอร์

---

## 3. API

Base URL: `http://127.0.0.1:5000`

| Method | Path | คำอธิบาย |
|--------|------|----------|
| GET  | `/` | หน้าเว็บหลัก |
| POST | `/api/design` | คำนวณแบบผังเสา |
| POST | `/api/export/csv` | คืนไฟล์ CSV (UTF-8 BOM, เปิดใน Excel ได้ทันที) |
| GET  | `/api/standards` | ตารางมาตรฐาน span ที่ใช้คำนวณ |
| GET  | `/api/sample` | เส้นทางตัวอย่างพร้อมจุดพิกัด |
| GET  | `/api/health` | ตรวจว่าเซิร์ฟเวอร์ทำงาน |

### POST `/api/design`

```json
{ "points": [[0,0],[200,0],[254.8,47.0],[400,47.0]],
  "offset": 5.0, "use_break_poles": true, "road_width": 16.0 }
```

| field | ชนิด | ค่าเริ่มต้น | ความหมาย |
|-------|------|-----------|----------|
| `points` | `[[x, y], ...]` | จำเป็น | centerline หน่วยเมตร อย่างน้อย 2 จุด |
| `offset` | number (0–50) | `5.0` | ระยะถอยจาก centerline เข้าหา R.O.W. |
| `use_break_poles` | bool | `true` | ใช้ break pole คู่หน้าหลังมุมเมื่อจำเป็น |
| `road_width` | number (0–50) | `16.0` | ความกว้างเขตทางจริง (ศูนย์ = ปิดกฎเว้นว่าง) |

**กฎเขตทาง:** ระบบคำนวณระยะเว้นว่างขั้นต่ำจากความกว้างถนนจริง
(`road_width / 2 + 2.0 m`) ถ้า offset ที่ขอมาน้อยกว่าเกณฑ์นี้
ระบบจะ **ถอยแนวเสาออกอัตโนมัติ** พร้อมแจ้ง warning และเก็บ
`requested_offset_m` ไว้เปรียบเทียบ

ตอบกลับ `200` (หรือ `400` พร้อมข้อความภาษาไทยเมื่อ input ผิด):

```jsonc
{
  "ok": true,
  "offset_m": 10.0,
  "requested_offset_m": 5.0,
  "road_width_m": 16.0,
  "road_clearance_m": 2.0,
  "min_edge_clearance_m": 2.0,
  "centerline": [[0,0], ...],
  "poles": [{ "id":1, "x":0, "y":10, "station":0.0,
              "code":"start", "type":"เสาดับสายต้นทาง DDE (Start Deadend)",
              "gy":true, "gy_angle":180.0,
              "gy_anchor_x":-10.0, "gy_anchor_y":10.0,
              "bracket":"(-O",
              "angle":0.0, "span_from_prev":null, "span_to_next":38.26,
              "marker":"D", "color":"#c0392b" }, ... ],
  "spans": [{ "length":38.26, "mid_x":19.13, "mid_y":10.0 }, ... ],
  "validation": [{ "label":"...", "value":"...", "status":"PASS" }, ... ],
  "warnings": ["ระยะ Offset ที่ขอ (5.00 m) ทำให้เสาอยู่ใกล้ขอบถนน ..."],
  "summary": { "length_m":200.0, "pole_count":9, "max_span_used_m":38.26,
               "guy_pole_count":5, "curve_pole_count":2,
               "count_label":"TANGENT=7 CURVE=2 ...", "tangent_max_span_m":40.0 }
}
```

ตัวอย่างเรียกด้วย PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/design -Method POST `
  -ContentType 'application/json' -Encoding UTF8 `
  -Body '{"points":[[0,0],[200,0],[254.8,47.0],[400,47.0]],"offset":5.0,"use_break_poles":true,"road_width":16.0}'
```

---

## 4. CLI

```bash
python pole_designer.py --help      # ดูตัวเลือกทั้งหมด
python pole_designer.py             # เปิดหน้าต่างคลิกวาดเส้นทางเอง (ต้องมีจอ GUI)
python pole_designer.py --demo      # ใช้เส้นทางตัวอย่าง 200 m
python pole_designer.py --demo --agg --save out.png --csv out.csv
python pole_designer.py --points "0,0;120,0;120,45;200,45" --offset 6 --agg --save a.png
```

| ตัวเลือก | ความหมาย |
|---------|----------|
| `--demo` | ใช้เส้นทางตัวอย่าง 200 m (100 m → เลี้ยว 90° 50 m → 50 m) |
| `--points "x,y;x,y;..."` | ระบุ centerline เอง เหมาะกับงาน batch |
| `--offset M` | ระยะถอยจาก centerline (ค่าเริ่มต้น 5.0) |
| `--road-width M` | ความกว้างเขตทางจริง (ค่าเริ่มต้น 16.0, 0 = ปิดกฎเว้นว่าง) |
| `--no-break` | ไม่ใช้ break pole ที่มุม |
| `--csv PATH` | บันทึกตารางเสาเป็น CSV (UTF-8 BOM) |
| `--save PATH` | บันทึกผังเป็น PNG |
| `--agg` | ไม่เปิดหน้าต่างกราฟ (batch/หัวเวร์เวอร์) |
| `--no-fallback` | ถ้าโหมด interactive ใช้ไม่ได้ ให้ error แทนการใช้เส้นตัวอย่าง |

CLI คืนรหัสจบกระบวนการ `0` เมื่อผ่านทุกเกณฑ์, `2` เมื่อมีเกณฑ์ไม่ผ่าน
(เหมาะกับงาน batch ที่ต้องเช็คผลในสคริปต์)

---

## 5. หลักศึกษาที่ระบบบังคับใช้

การออกแบบถูกตรวจสอบ 7 เกณฑ์ทุกครั้งที่คำนวณ ผลแสดงในทั้งเว็บและ CLI

| เกณฑ์ | ค่าที่ใช้ |
|-------|---------|
| R.O.W. offset | ถอยจาก centerline เข้าหาเขตสาย (ค่าเริ่มต้น 5.0 m, กำหนดได้ 0–50 m) — **เสาหักมุมอยู่ที่จุดตัดของแนว offset ทั้งสองช่วง** จึงห่างขอบถนนเท่ากับ offset ทั้งสองด้านของมุมเสมอ |
| เขตทาง / เว้นว่าง | เสาต้องห่างริมทาง ≥ 2.0 m (`offset ≥ road_width/2 + 2.0`) — ระบบถอยแนวเสาอัตโนมัติถ้าขอมาน้อยเกิน |
| Max span (ช่วงตรง) | 40 / 35 / 25 / 20 m ตามมุมงอ 0–10°, 10–30°, 30–60°, >60° |
| Slack span บนช่วงโค้ง | ≤ 20 m ทุกช่อง BA / SA / MA / LA |
| TG บนช่วง PC–PT | ห้ามมี (ต้น TG อยู่เฉพาะช่วงตรง) |
| Bracket | Start `(-O`, End `O-)`, เสากลาง `---O---` สมดุลแรงดึงสองด้าน |
| สายยึดโยง + สมอบก | เสาต้นทาง/ปลายทาง/มุม (curve/BA)/break ยึด GY-21 พร้อมสมอบก — ทิศทางลาก **ขนานตามแนว R.O.W. หลังเสา (หันเข้าหาเสาเพื่อนบ้านช่วงที่สั้นกว่า** `heading(pole→neighbor)`**)**: เสาดับสายปลายทาง (ตันสุดเส้น) กลับทิศ 180° เพื่อสมอบกอยู่ฝั่ง "นอกเส้น"; เสามุมใช้ทิศช่วงที่สั้นกว่าเพื่อสมอบกอยู่ฝั่งที่ถูกต้องของถนน — สมอบกอีกทั้งสองกรณีไม่หลุดเข้าไปบนผิวจราจร |
| Break pole | แทรกเฉพาะเมื่อมุมงอ **≥ 30°** (`ANGLE_BREAK_MIN`) — มุมเล็ก/กลางแค่นุ่มๆ ไม่ต้องใช้ |

ข้อความเตือน (**warnings**) ที่ระบบแจ้งเพิ่มเติมนอกเหนือจาก 7 เกณฑ์ เช่น

- offset ที่ขอมาน้อยกว่าเกณฑ์เขตทาง → ระบบถอยแนวเสาออกอัตโนมัติ
- ช่วง Slack ระหว่างเสาหักมุมยาวเกิน 20 m
- เสาหักมุมสองต้นอยู่ติดกันจนควรพิจารณารวมจุดหัก
- ได้เสาน้อยกว่า 2 ต้น (แนวเส้นทางสั้นเกินไป)

---

## 6. โครงสร้างไฟล์

```
Pole-Line-Designer/
├─ line_engine.py          แกนการคำนวณ (Polyline, design, validate, payload, CSV)
├─ app.py                  Flask API + เสิร์ฟหน้าเว็บ
├─ pole_designer.py        CLI แบบ matplotlib (import จาก line_engine)
├─ web/
│  ├─ templates/index.html
│  └─ static/
│     ├─ css/style.css
│     ├─ js/app.js         Canvas, interaction, API, export, localStorage
│     └─ js/pyodide-bridge.js   ตอบ /api/* ในเบราว์เซอร์ (static build เท่านั้น)
├─ docs/                   build หน้า static สำหรับ GitHub Pages (สร้างด้วย build_static.py)
├─ tests/
│  ├─ test_engine.py       ทดสอบเอนจิน + ตารางมาตรฐาน
│  └─ test_api.py          ทดสอบ endpoint ทั้งหมด
├─ run_tests.py            รันชุดทดสอบทั้งหมด (69 เคส)
├─ test_standards.py       ชุด regression 11 กรณี พร้อมตารางผล
├─ check_frontend.py       ตรวจหน้าเว็บ (id/payload ครบ + รัน app.js ใน DOM จำลอง)
├─ build_static.py         build หน้า static ลง docs/ พร้อม self-check
├─ check_static.py         E2E ทดสอบหน้า static ด้วยเบราว์เซอร์จริง (Pyodide)
└─ smoke_live.py           ทดสอบ HTTP จริงกับเซิร์ฟเวอร์ที่รันอยู่
```

---

## 7. การทดสอบ

```bash
python -X utf8 run_tests.py            # 69 เคส (engine + API)
python -X utf8 test_standards.py       # regression 11 กรณี พร้อมตารางเทียบ
python -X utf8 check_frontend.py       # ตรวจหน้าเว็บ 33 รายการ
python -X utf8 smoke_live.py           # HTTP จริง (ต้องเปิดเซิร์ฟเวอร์ก่อน)
python -X utf8 check_static.py         # E2E หน้า static + Pyodide + ด่านภาพพื้นหลัง (เบราว์เซอร์จริง)
python -X utf8 check_static.py --url https://icem79ai-ops.github.io/pole-line-designer/   # ทดสอบ URL ที่ publish แล้ว
```

`smoke_live.py` ต้องรันคู่กับเซิร์ฟเวอร์:

```bash
python app.py --no-browser --port 5123      # ค้างไว้ในอีกหน้าต่าง
python smoke_live.py --port 5123
```

หมายเหตุบน Windows: ใช้ `python -X utf8` เพื่อไม่ให้ภาษาไทยใน console เพี้ยน

---

## 8. ข้อมูลอ้างอิงที่ฝังไว้ในระบบ

- โค้ดชนิดเสา/ป้าย/สีสำหรับ Start Deadend, Tangent, Curve (BA/SA/MA/LA),
  Break, Guy และสมอบก — ดูรายละเอียดที่ `line_engine.standards_reference()`
  หรือเรียก `GET /api/standards`
- ตารางประสิทธิภาพ span ตามมุมงออยู่ใน `line_engine.max_span_for_angle()`

---

## 9. ลิขสิทธิ์

ซอฟต์แวร์นี้เป็น **ลิขสิทธิ์ทรัพย์สินของผู้เขียน** (สงวนสิทธิ์ทุกประการ)

- ดูโค้ด / ศึกษา / รันทดลองส่วนตัวได้
- **ใช้เพื่อการค้า แจกจ่าย ขายต่อ หรือนำไปเป็นผลงานของตนไม่ได้**
  หากไม่ได้รับอนุญาตเป็นลายลักษณ์อักษรก่อน
- ขออนุญาตได้โดยเปิด issue บน GitHub ของ repository นี้

รายละเอียดครบอ่านที่ [`LICENSE`](LICENSE)
