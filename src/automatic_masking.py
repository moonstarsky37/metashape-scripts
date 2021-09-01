# This is python script for Metashape Pro. Scripts repository: https://github.com/agisoft-llc/metashape-scripts
#
# Based on https://github.com/danielgatis/rembg (tested on rembg==1.0.27)
#
# How to install (Linux):
#
# 1. cd .../metashape-pro
#    LD_LIBRARY_PATH=`pwd`/python/lib/ python/bin/python3.8 -m pip install rembg torch==1.9.0+cu111 torchvision==0.10.0+cu111 torchaudio==0.9.0 -f https://download.pytorch.org/whl/torch_stable.html
# 2. Add this script to auto-launch - https://agisoft.freshdesk.com/support/solutions/articles/31000133123-how-to-run-python-script-automatically-on-metashape-professional-start
#    copy automatic_masking.py script to /home/<username>/.local/share/Agisoft/Metashape Pro/scripts/
#
# How to install (Windows):
#
# 1. Launch cmd.exe with the administrator privileges
# 2. "%programfiles%\Agisoft\Metashape Pro\python\python.exe" -m pip install rembg torch==1.9.0+cu111 torchvision==0.10.0+cu111 torchaudio===0.9.0 -f https://download.pytorch.org/whl/torch_stable.html
# 3. Add this script to auto-launch - https://agisoft.freshdesk.com/support/solutions/articles/31000133123-how-to-run-python-script-automatically-on-metashape-professional-start
#    copy automatic_masking.py script to C:/Users/<username>/AppData/Local/Agisoft/Metashape Pro/scripts/

import pathlib
import Metashape
import multiprocessing
import concurrent.futures

# Checking compatibility
compatible_major_version = "1.7"
found_major_version = ".".join(Metashape.app.version.split('.')[:2])
if found_major_version != compatible_major_version:
    raise Exception("Incompatible Metashape version: {} != {}".format(found_major_version, compatible_major_version))

# Supported >= 1.7.4
if int(Metashape.app.version.split('.')[2]) < 4:
    raise Exception("Incompatible Metashape version: {} found, but >= 1.7.4 required".format(Metashape.app.version))


def generate_automatic_background_masks_with_rembg():
    try:
        import rembg
        import rembg.bg
        import scipy
        import numpy as np
        import io
        from PIL import Image
    except ImportError:
        print("Please ensure that you installed torch and rembg - see instructions in the script")
        raise

    print("Script started...")
    doc = Metashape.app.document
    chunk = doc.chunk

    cameras = chunk.cameras

    nmasks_exists = 0
    for c in cameras:
        if c.mask is not None:
            nmasks_exists += 1
            print("Camera {} already has mask".format(c.label))
    if nmasks_exists > 0:
        raise Exception("There are already {} masks, please remove them and try again".format(nmasks_exists))

    masks_dirs_created = set()
    cameras_by_masks_dir = {}
    for i, c in enumerate(cameras):
        input_image_path = c.photo.path
        image_mask_dir = pathlib.Path(input_image_path).parent / 'masks'
        if image_mask_dir.exists() and str(image_mask_dir) not in masks_dirs_created:
            attempt = 2
            image_mask_dir_attempt = pathlib.Path(str(image_mask_dir) + "_{}".format(attempt))
            while image_mask_dir_attempt.exists() and str(image_mask_dir_attempt) not in masks_dirs_created:
                attempt += 1
                image_mask_dir_attempt = pathlib.Path(str(image_mask_dir) + "_{}".format(attempt))
            image_mask_dir = image_mask_dir_attempt
        if image_mask_dir.exists():
            assert str(image_mask_dir) in masks_dirs_created
        else:
            image_mask_dir.mkdir(parents=False, exist_ok=False)
            masks_dirs_created.add(str(image_mask_dir))
            cameras_by_masks_dir[str(image_mask_dir)] = list()
        cameras_by_masks_dir[str(image_mask_dir)].append(c)

    torch_lock = multiprocessing.Lock()

    def process_camera(image_mask_dir, c, camera_index):
        input_image_path = c.photo.path
        print("{}/{} processing: {}".format(camera_index + 1, len(cameras), input_image_path))
        image_mask_name = pathlib.Path(input_image_path).name.split(".")
        if len(image_mask_name) > 1:
            image_mask_name = image_mask_name[:-1]
        image_mask_name = ".".join(image_mask_name)

        image_mask_path = str(image_mask_dir / image_mask_name) + "_mask.png"

        photo_image = c.photo.image()
        img = np.frombuffer(photo_image.tostring(), dtype={'U8': np.uint8, 'U16': np.uint16}[photo_image.data_type]).reshape(photo_image.height, photo_image.width, photo_image.cn)[:, :, :3]
        model_name = "u2net"
        with torch_lock:
            model = rembg.bg.get_model(model_name)
            mask = rembg.u2net.detect.predict(model, img).convert("L")
        mask = np.array(mask.resize((photo_image.width, photo_image.height)))

        mask = (mask > 10)
        mask = scipy.ndimage.morphology.binary_dilation(mask, iterations=3)
        mask = scipy.ndimage.morphology.binary_erosion(mask, iterations=3)
        mask = mask.astype(np.uint8) * 255
        mask = np.dstack([mask, mask, mask])

        Image.fromarray(mask).save(image_mask_path)
        Metashape.app.update()

    with concurrent.futures.ThreadPoolExecutor(4) as executor:
        camera_offset = 0
        futures = []
        for masks_dir, dir_cameras in cameras_by_masks_dir.items():
            for camera_index, c in enumerate(dir_cameras):
                futures.append(executor.submit(process_camera, pathlib.Path(masks_dir), c, camera_offset + camera_index))
            camera_offset += len(dir_cameras)

        concurrent.futures.wait(futures)
        for future in futures:
            future.result()  # to check for exceptions

    print("{} masks generated in {} directories:".format(len(cameras), len(masks_dirs_created)))
    for mask_dir in sorted(masks_dirs_created):
        print(mask_dir)

    print("Importing masks into project...")
    for masks_dir, dir_cameras in cameras_by_masks_dir.items():
        chunk.generateMasks(path=masks_dir + "/{filename}_mask.png", masking_mode=Metashape.MaskingMode.MaskingModeFile, cameras=dir_cameras)

    print("Script finished.")


label = "Custom Menu/Automatic background masking"
Metashape.app.addMenuItem(label, generate_automatic_background_masks_with_rembg)
print("To execute this script press {}".format(label))