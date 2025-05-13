import os


def getChildPath(localRootDir,path):
    # 获取指定目录下的所有文件和子目录

    if path == '/':
        path = localRootDir


    file_list = os.listdir(path)

    if file_list is not None:
        dirs_only = [f for f in file_list if os.path.isdir(os.path.join(localRootDir, f))]

        if dirs_only is not None:
            var = [{'path': path+'/'+item} for item in dirs_only ]

            return var
        else:
            return []
    else:
        return []



def getLocalRootDir():
    # 获取指定目录下的所有文件和子目录
    localRootDir = '/tmp'

    res = os.listdir(localRootDir)

    dirs_only = [f for f in res if os.path.isdir(os.path.join(localRootDir, f))]

    if dirs_only is not None:
        var = [{'path': item} for item in dirs_only ]
        return var
    else:
        return []




