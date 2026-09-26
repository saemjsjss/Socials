import os
import io
import time
import pymupdf
from PIL import Image

TARGET_DIR = r"E:\drive-download-20260917T042358Z-1-001"
MAX_SIZE_BYTES = int(1.95 * 1024 * 1024)  # 1.95 MB to safely guarantee strictly under 2.0 MB

def compress_pdf(file_path):
    orig_size = os.path.getsize(file_path)
    if orig_size <= MAX_SIZE_BYTES:
        return False, orig_size, orig_size

    try:
        doc = pymupdf.open(file_path)
    except Exception as e:
        print(f"   [Error opening] {file_path}: {e}")
        return False, orig_size, orig_size

    num_pages = len(doc)
    tmp_path = file_path + ".tmp.pdf"

    # Profiles (dpi, jpeg_quality)
    profiles = [
        (135, 75),
        (120, 70),
        (110, 65),
        (95, 60),
        (85, 55),
        (75, 50)
    ]

    if num_pages > 25:
        profiles = profiles[2:]
    elif num_pages > 15:
        profiles = profiles[1:]

    success = False
    best_size = orig_size

    for dpi, quality in profiles:
        new_doc = pymupdf.open()
        try:
            for page_idx in range(num_pages):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)

                rect = page.rect
                new_page = new_doc.new_page(width=rect.width, height=rect.height)
                new_page.insert_image(rect, stream=buf.getvalue())

            new_doc.save(tmp_path, deflate=True, garbage=4)
            new_doc.close()

            new_size = os.path.getsize(tmp_path)
            best_size = new_size

            if new_size <= MAX_SIZE_BYTES:
                success = True
                break
        except Exception as e:
            if not new_doc.is_closed:
                new_doc.close()
            print(f"   [Error processing profile {dpi}/{quality}]: {e}")

    doc.close()

    if success and os.path.exists(tmp_path) and os.path.getsize(tmp_path) <= MAX_SIZE_BYTES:
        os.replace(tmp_path, file_path)
        return True, orig_size, best_size
    else:
        # If best attempt was smaller than original even if slightly above threshold, use it or clean up
        if os.path.exists(tmp_path):
            if best_size < orig_size:
                os.replace(tmp_path, file_path)
                return True, orig_size, best_size
            else:
                os.remove(tmp_path)
        return False, orig_size, best_size

def compress_image(file_path):
    orig_size = os.path.getsize(file_path)
    if orig_size <= MAX_SIZE_BYTES:
        return False, orig_size, orig_size

    tmp_path = file_path + ".tmp.jpg"
    try:
        with Image.open(file_path) as img:
            img = img.convert("RGB")
            quality = 85
            while quality >= 30:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                if len(buf.getvalue()) <= MAX_SIZE_BYTES:
                    with open(tmp_path, "wb") as f:
                        f.write(buf.getvalue())
                    os.replace(tmp_path, file_path)
                    return True, orig_size, len(buf.getvalue())
                quality -= 10
    except Exception as e:
        print(f"   [Error compressing image] {file_path}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return False, orig_size, orig_size

def main():
    print("=" * 60)
    print(f"Target Directory: {TARGET_DIR}")
    print(f"Max Target Size : 2.00 MB ({MAX_SIZE_BYTES} bytes)")
    print("=" * 60)

    start_time = time.time()
    total_files = 0
    skipped_under_2mb = 0
    compressed_count = 0
    failed_count = 0
    total_saved_bytes = 0

    all_tasks = []
    for root, dirs, files in os.walk(TARGET_DIR):
        for f in files:
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            ext = os.path.splitext(f)[1].lower()
            all_tasks.append((fp, sz, ext, f, os.path.basename(root)))

    total_files = len(all_tasks)
    print(f"Found {total_files} total files across all folders.\n")

    for idx, (fp, sz, ext, fname, folder_name) in enumerate(all_tasks, 1):
        if sz <= MAX_SIZE_BYTES:
            skipped_under_2mb += 1
            continue

        orig_mb = sz / (1024 * 1024)
        print(f"[{idx}/{total_files}] {folder_name} / {fname} ({orig_mb:.2f} MB)")

        if ext == ".pdf":
            ok, old_s, new_s = compress_pdf(fp)
        elif ext in [".jpg", ".jpeg", ".png"]:
            ok, old_s, new_s = compress_image(fp)
        else:
            print(f"   Skipping unsupported format: {ext}")
            continue

        if ok:
            new_mb = new_s / (1024 * 1024)
            saved_mb = (old_s - new_s) / (1024 * 1024)
            total_saved_bytes += (old_s - new_s)
            compressed_count += 1
            print(f"   -> Successfully compressed: {new_mb:.2f} MB (saved {saved_mb:.2f} MB)")
        else:
            failed_count += 1
            print(f"   -> Could not compress below 2MB. Kept original.")

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("COMPRESSION SUMMARY")
    print("=" * 60)
    print(f"Total Files Scanned      : {total_files}")
    print(f"Untouched (Already < 2MB): {skipped_under_2mb}")
    print(f"Successfully Compressed  : {compressed_count}")
    print(f"Failed / Unchanged       : {failed_count}")
    print(f"Total Storage Saved      : {total_saved_bytes / (1024 * 1024):.2f} MB")
    print(f"Time Taken               : {elapsed:.1f} seconds")
    print("=" * 60)

if __name__ == "__main__":
    main()
