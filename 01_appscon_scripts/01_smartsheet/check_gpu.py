# check_gpu.py

import torch
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

def main():
    has_cuda = torch.cuda.is_available()
    device_count = torch.cuda.device_count()
    current_device = torch.cuda.current_device() if has_cuda else None
    device_name = torch.cuda.get_device_name(current_device) if has_cuda else None

    print(f"CUDA disponible: {has_cuda}")
    print(f"Número de GPUs detectadas: {device_count}")
    if has_cuda:
        print(f"GPU actual (índice {current_device}): {device_name}")

if __name__ == "__main__":
    main()