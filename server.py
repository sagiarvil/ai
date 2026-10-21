#!/usr/bin/env python3
"""
BARIŞ AI // ANA SUNUCU ÇALIŞTIRICI
Yönetilen yerel başlatıcıya yönlendirir; varsayılan port 5053'tür.
"""

from durable_api import app

if __name__ == "__main__":
    from baris_local import main
    main()

