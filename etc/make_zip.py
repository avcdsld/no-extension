import zipfile
from pathlib import Path

OUTPUT_ZIP = Path("demo/zip/input.zip")

with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_STORED) as zf:
    for name in ["this/", "this/is/", "this/is/not/", "this/is/not/a/",
                  "this/is/not/a/transaction"]:
        info = zipfile.ZipInfo(name)
        info.date_time = (1980, 1, 1, 0, 0, 0)  # null
        zf.writestr(info, "")

print(f"生成: {OUTPUT_ZIP}")
print(f"確認: unzip -l {OUTPUT_ZIP}")
