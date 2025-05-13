import logging


from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT

import os
import io


# 工具类：提供SM4加解密以及填充处理
class AlgorithmTool:
    def __init__(self):
        pass

    # 将16进制字符串转换为字节数据
    @staticmethod
    def hex_string_to_bytes(data):
        return data

    # PKCS7填充算法，确保数据长度是16字节的整数倍
    def pkcs7_padding(self, data):
        pad_len = 16 - (len(data) % 16)  # 计算需要填充的字节数
        padding = bytes([pad_len] * pad_len)  # 生成填充字节
        return data + padding  # 将填充字节附加到数据末尾

    # 去除PKCS7填充，恢复原始数据
    def pkcs7_unpadding(self, data):
        pad_len = data[-1]  # 读取最后一个字节，获取填充长度
        return data[:-pad_len]  # 移除填充字节

    # 使用SM4进行ECB模式加密
    def encrypt_sm4(self, key, value):
        crypt_sm4 = CryptSM4()
        crypt_sm4.set_key(self.hex_string_to_bytes(key), SM4_ENCRYPT)  # 设置加密密钥
        return crypt_sm4.crypt_ecb(value)  # 返回加密后的字节数据

    # 使用SM4进行ECB模式解密
    def decrypt_sm4(self, key, encrypted_value):
        crypt_sm4 = CryptSM4()
        crypt_sm4.set_key(self.hex_string_to_bytes(key), SM4_DECRYPT)  # 设置解密密钥
        decrypted_data = crypt_sm4.crypt_ecb(encrypted_value)  # 进行解密
        return self.pkcs7_unpadding(decrypted_data)  # 去除填充，返回解密后的数据



# 文件加密辅助类：提供按块加密和解密大文件的功能
class SM4FileHelper:

    def __init__(self, encryptKey):
        if len(encryptKey) != 32:
            raise ValueError("密码格式不对")
        self.ag_tool = AlgorithmTool()  # 使用AlgorithmTool处理加解密
        self.key = encryptKey[6:22].upper().encode('utf-8')
        self.block_size = 16 * 1024  # 块大小为16的倍数


    # 加密文件，并在文件开头保存原始文件大小信息
    def encrypt_file(self, input_file_path, output_file_path):
        """按块加密文件内容，并在文件开头存储原始文件大小"""
        logger = logging.getLogger()

        try:
            # 获取输入文件的总大小
            file_size = os.path.getsize(input_file_path)

            # 打开输入和输出文件
            with open(input_file_path, 'rb') as f_in, open(output_file_path, 'wb') as f_out:
                # 写入文件大小，便于解密时恢复
                f_out.write(file_size.to_bytes(8, byteorder='big'))

                # 循环按块读取文件
                while True:
                    chunk = f_in.read(self.block_size)  # 读取数据块
                    if not chunk:
                        break  # 如果没有数据，则结束循环

                    if len(chunk) < self.block_size:
                        # 如果是最后一个块，进行填充后加密
                        padded_chunk = self.ag_tool.pkcs7_padding(chunk)
                        encrypted_chunk = self.ag_tool.encrypt_sm4(self.key, padded_chunk)
                    else:
                        # 如果是完整的块，直接加密
                        encrypted_chunk = self.ag_tool.encrypt_sm4(self.key, chunk)

                    f_out.write(encrypted_chunk)  # 写入加密后的数据

            return True
        except IOError as e:
            logger.error(f"文件操作错误: {e}")# 处理文件读写错误
            return False
        except Exception as e:
            logger.error(f"加密过程中的错误: {e}")  # 处理加密过程中的其他异常
            return False

    # 解密文件，并恢复原始文件内容
    def decrypt_file(self, input_file_path, output_file_path):
        logger = logging.getLogger()
        """按块解密文件内容"""
        try:

            # 打开输入和输出文件
            with open(input_file_path, 'rb') as f_in_raw, open(output_file_path, 'wb') as f_out:
                f_in = io.BufferedReader(f_in_raw)

                # 读取文件开头的原始文件大小
                original_file_size = int.from_bytes(f_in.read(8), byteorder='big')

                decrypted_size = 0  # 已解密的数据大小

                # 循环按块解密文件
                while True:
                    encrypted_chunk = f_in.read(self.block_size + 16)  # 读取加密数据块
                    if not encrypted_chunk:
                        break  # 如果没有数据，则结束循环

                    if f_in.peek(1) == b'':  # 判断是否为最后一个块
                        # 最后一个块，进行解密后去填充，并调整大小
                        decrypted_chunk = self.ag_tool.decrypt_sm4(self.key, encrypted_chunk)
                        remaining_size = original_file_size - decrypted_size  # 计算剩余未写入的大小
                        decrypted_chunk = decrypted_chunk[:remaining_size]  # 截断填充后的多余数据
                    else:
                        # 非最后一个块，直接解密
                        decrypted_chunk = self.ag_tool.decrypt_sm4(self.key, encrypted_chunk)
                    f_out.write(decrypted_chunk)  # 写入解密后的数据
                    decrypted_size += len(decrypted_chunk)  # 更新已解密数据的大小
            return True
        except IOError as e:
            logger.error(f"文件操作错误: {e}")  # 处理文件读写错误
            return False
        except Exception as e:
            logger.error(f"解决密过程中的错误: {e}")  # 处理加密过程中的其他异常
            return False