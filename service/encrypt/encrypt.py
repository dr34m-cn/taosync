import os
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT


class SM4FileCrypto:

    def __init__(self, key):
        """
        初始化SM4文件加密器
        :param key: 16字节密钥
        :param iv: 16字节初始化向量，None则随机生成
        """
        if len(key) != 32:
            raise ValueError("密码格式不对")
        self.key = key[6:22].upper().encode('utf-8')
        self.iv = key[16:32].upper().encode('utf-8')
        self.cipher = CryptSM4()
        self.cipher.set_key(self.key, SM4_ENCRYPT)
        self.block_size = 16  # SM4分组大小
        self.counter = 0


    def _generate_key_stream(self):
        """生成密钥流块"""
        ctr_block = self.iv + self.counter.to_bytes(4, 'big')
        self.counter += 1
        return self.cipher.crypt_ecb(ctr_block)

    def encrypt_file(self, input_file, output_file, chunk_size=8*1024 * 1024):
        """
        加密文件
        :param input_file: 输入文件路径
        :param output_file: 输出文件路径
        :param chunk_size: 每次处理的块大小(字节)
        """
        print(f'enptkey:{self.key}')
        print(f'input_file:{input_file}')
        print(f'output_file:{output_file}')

        with open(input_file, 'rb') as fin, open(output_file, 'wb') as fout:
            # 首先写入IV，解密时需要
            fout.write(self.iv)

            while True:
                chunk = fin.read(chunk_size)
                if not chunk:
                    break

                encrypted_chunk = bytearray()
                for i in range(0, len(chunk), self.block_size):
                    block = chunk[i:i + self.block_size]
                    key_stream = self._generate_key_stream()
                    encrypted_block = bytes(b ^ k for b, k in zip(block, key_stream[:len(block)]))
                    encrypted_chunk.extend(encrypted_block)

                fout.write(encrypted_chunk)

    def decrypt_file(self, input_file, output_file, chunk_size=8*1024 * 1024):

        print(f'enptkey:{self.key}')
        print(f'input_file:{input_file}')
        print(f'output_file:{output_file}')

        """
        解密文件(加密和解密过程相同)
        """
        with open(input_file, 'rb') as fin:
            # 读取IV
            iv = fin.read(16)
            if len(iv) != 16:
                raise ValueError("无效的加密文件格式")

            # 重置IV和计数器
            self.iv = iv
            self.counter = 0

            with open(output_file, 'wb') as fout:
                while True:
                    chunk = fin.read(chunk_size)
                    if not chunk:
                        break

                    decrypted_chunk = bytearray()
                    for i in range(0, len(chunk), self.block_size):
                        block = chunk[i:i + self.block_size]
                        key_stream = self._generate_key_stream()
                        decrypted_block = bytes(b ^ k for b, k in zip(block, key_stream[:len(block)]))
                        decrypted_chunk.extend(decrypted_block)

                    fout.write(decrypted_chunk)
        print(f'解密完成:{output_file}')