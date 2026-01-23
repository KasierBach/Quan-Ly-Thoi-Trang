
import shutil
import os

def apply_fixes():
    static_images_dir = r"d:\SQL\dbmstestfileshit\thua 2.0\app\static\images"
    artifact_path = r"C:/Users/Admin/.gemini/antigravity/brain/c64ac526-2ea6-422f-ac22-6de843b4f773/23_1769170679005.png"
    
    # 1. Apply generated image for ID 23
    dest_23 = os.path.join(static_images_dir, "23.png")
    if os.path.exists(artifact_path):
        shutil.copy(artifact_path, dest_23)
        print(f"Copied generated image to {dest_23}")
    else:
        print(f"Artifact not found at {artifact_path}")

    # 2. Fallback for ID 26 (Copy quan-nu.jpg)
    src_26_fallback = os.path.join(static_images_dir, "quan-nu.jpg")
    dest_26 = os.path.join(static_images_dir, "26.jpg")
    if os.path.exists(src_26_fallback):
        shutil.copy(src_26_fallback, dest_26)
        print(f"Copied fallback {src_26_fallback} to {dest_26}")
    else:
        print(f"Fallback source {src_26_fallback} not found")

    # 3. Fix missing default-product.png (Copy default.jpg)
    # Note: This creates a file named .png but containing JPEG data. Browsers usually handle this.
    src_default = os.path.join(static_images_dir, "default.jpg")
    dest_default = os.path.join(static_images_dir, "default-product.png")
    if os.path.exists(src_default):
        shutil.copy(src_default, dest_default)
        print(f"Copied {src_default} to {dest_default}")
    else:
        print(f"Default source {src_default} not found")

if __name__ == "__main__":
    apply_fixes()
