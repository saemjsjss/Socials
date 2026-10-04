import torch

if torch.cuda.is_available():
    free, total = torch.cuda.mem_get_info()
    print(torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))
    print(free, total)
else:
    print("no-cuda")
    print(0, 0)
