# Customize the PDF Export

PDF generation lives in `src/app.py` in helper functions named `_build_*_pdf()`. Each report (devices, services, CTR servers, printers) has its own builder using [`fpdf2`](https://py-pdf.github.io/fpdf2/).

## Where to look

```python
# src/app.py
def _build_devices_pdf(devices, filters):
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    # ... layout code ...
    return bytes(pdf.output())

def _build_services_pdf(services):
    # ...

def _build_ctr_pdf(hosts, vms):
    # ...
```

The corresponding routes (`/export/pdf`, `/export/services/pdf`, `/export/ctr/pdf`, `/export/printers/csv` for CSV) call these helpers and stream the result back to the browser.

## Common changes

### Change page orientation

```python
# Portrait A4 instead of landscape
pdf = FPDF(orientation="P", unit="mm", format="A4")
```

### Custom logo

```python
# Add a logo at the top of every page
pdf.add_page()
pdf.image("static/img/logo.png", x=10, y=8, w=30)
pdf.set_y(40)  # Move cursor below the logo
```

### Different font

`fpdf2` ships with a few core fonts (Helvetica, Times, Courier) that are Latin-1 encoded. For UTF-8 support, register a TrueType font:

```python
pdf.add_font("Inter", style="", fname="static/fonts/Inter-Regular.ttf", uni=True)
pdf.add_font("Inter", style="B", fname="static/fonts/Inter-Bold.ttf", uni=True)
pdf.set_font("Inter", size=10)
```

The `safe()` helper in `src/app.py` currently encodes strings to Latin-1 — remove that call once you switch to a UTF-8 font.

### Add a column

```python
# Inside _build_devices_pdf:
columns = [
    ("Device", 60),
    ("Manufacturer", 35),
    ("Model", 40),
    ("Serial", 35),
    ("Status", 20),
    ("VPN", 15),
    ("Inventory", 25),    # ← new column
]

# Make sure the data row writes into the new column too:
pdf.cell(25, row_height, str(device.get("inventory_no") or "—"), border=1)
```

### Different colour scheme

```python
pdf.set_fill_color(25, 95, 161)  # header background — RGB
pdf.set_text_color(255, 255, 255)  # header text
# ... write header row ...
pdf.set_fill_color(255, 255, 255)
pdf.set_text_color(0, 0, 0)
```

### Custom footer

`fpdf2` calls `footer()` on every page. Subclass `FPDF`:

```python
class InventoryPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()} of {{nb}}", align="C")

# Then in the builder:
pdf = InventoryPDF(orientation="L", format="A4")
pdf.alias_nb_pages()
```

## Adding a new report type

Steps:

1. **Builder function** in `src/app.py`:
   ```python
   def _build_my_report_pdf(rows: list[dict]) -> bytes:
       pdf = FPDF(...)
       # ... layout ...
       return bytes(pdf.output())
   ```

2. **Route** in `src/app.py`:
   ```python
   @app.get("/export/my-report/pdf")
   async def export_my_report_pdf():
       with get_db() as conn:
           rows = conn.execute("SELECT ... FROM ...").fetchall()
       data = _build_my_report_pdf([dict(r) for r in rows])
       filename = f"my-report-{datetime.now():%Y%m%d}.pdf"
       return Response(
           data,
           media_type="application/pdf",
           headers={"Content-Disposition": f'attachment; filename="{filename}"'},
       )
   ```

3. **UI link** in the relevant Jinja template:
   ```html
   <a href="/export/my-report/pdf" class="btn-export">Export PDF</a>
   ```

4. **Test** in `tests/test_pdf_export.py`:
   ```python
   def test_my_report_pdf(client, auth_cookie):
       response = client.get("/export/my-report/pdf",
                             cookies={"inventory_auth": auth_cookie})
       assert response.status_code == 200
       assert response.content[:4] == b"%PDF"
   ```

## fpdf2 reference

- Documentation: <https://py-pdf.github.io/fpdf2/>
- Cookbook: <https://py-pdf.github.io/fpdf2/Tutorial.html>
- Methods most used here: `add_page()`, `set_font()`, `cell()`, `multi_cell()`, `set_fill_color()`, `image()`
