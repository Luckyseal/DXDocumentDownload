import os
import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfFileMerger, PdfFileReader
from PIL import Image
import json
from urllib.parse import parse_qs, urlparse
import asyncio
import aiohttp
import pandas as pd

import re
import string

def sanitize_filename(filename, replace_with="_"):
    """
    将无效的Windows文件名字符替换为有效字符。
    :param filename: 原始文件名
    :param replace_with: 用于替换无效字符的字符
    :return: 符合Windows文件名规范的新文件名
    """
    try:
        # 删除文件名中的无效字符
        valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
        cleaned_filename = "".join(c if c in valid_chars else replace_with for c in filename)

        # 删除文件名中的保留字符
        reserved_names = ['con', 'prn', 'aux', 'nul'] + [f"com{i}" for i in range(10)] + [f"lpt{i}" for i in range(10)]
        cleaned_filename = re.sub(r'^(?i)(' + '|'.join(reserved_names) + r')\.?', replace_with, cleaned_filename)

        # 删除文件名前后的空格和点号
        cleaned_filename = cleaned_filename.strip(" .")

        # 如果文件名为空,返回默认名称
        if not cleaned_filename:
            cleaned_filename = "default_filename"

        return cleaned_filename
    except Exception as e:
        print(f"Error occurred while sanitizing filename: {e}")
        return filename

async def download_image(session, img_url, file_name):
    try:
        async with session.get(img_url) as response:
            if response.status == 200:
                img_data = await response.read()
                with open(file_name, "wb") as f:
                    f.write(img_data)
                print(f"Downloaded image: {file_name}")
            else:
                print(f"Failed to download image: {img_url}")
    except Exception as e:
        print(f"Error occurred while downloading image {img_url}: {e}")


# 异步函数，用于下载图片
async def download_images(url, save_root_path, img_classes):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    response_text = await response.text()
                else:
                    print(f"Failed to fetch URL: {url}")
                    return None, None

            soup = BeautifulSoup(response_text, "html.parser")

            folder_name = soup.find("h1", class_="rich_media_title")
            if folder_name:
                folder_name = folder_name.text.strip().replace("\\n", "")
            else:
                print(f"Unable to find folder name in URL: {url}")
                return None, None

            save_dir = os.path.join(save_root_path, sanitize_filename(folder_name))
            os.makedirs(save_dir, exist_ok=True)

            img_tags = soup.find_all("img", class_=img_classes)

            tasks = []
            for i, img_tag in enumerate(img_tags, start=1):
                if int(img_tag.get("data-w", 0)) < 1000:
                    continue

                img_url = img_tag.get("data-src")
                if not img_url:
                    continue

                parsed_url = urlparse(img_url)
                query_params = parse_qs(parsed_url.query)

                wx_fmt = query_params.get("wx_fmt")
                if wx_fmt:
                    wx_fmt = wx_fmt[0]
                else:
                    wx_fmt = "jpg"

                img_name = os.path.join(save_dir, f"{i}.{wx_fmt}")

                if os.path.exists(img_name):
                    print(f"Image {img_name} already exists.")
                    continue

                task = asyncio.create_task(download_image(session, img_url, img_name))
                tasks.append(task)

            await asyncio.gather(*tasks)

        return save_dir, folder_name
    except Exception as e:
        print(f"Error occurred while downloading images: {e}")
        return None, None


def convert_image_to_pdf(image_path, pdf_path):
    image = Image.open(image_path)
    image.save(pdf_path, "PDF", resolution=100.0)


def merge_pdfs(pdf_paths, output_path):
    # 创建一个PdfFileMerger对象
    merger = PdfFileMerger()

    # 遍历pdf_paths中的每一个pdf文件
    for pdf_path in pdf_paths:
        # 以二进制模式打开pdf文件
        with open(pdf_path, "rb") as file:
            # 创建一个PdfFileReader对象
            pdf_reader = PdfFileReader(file)
            # 将pdf_reader添加到merger中
            merger.append(pdf_reader)

    # 以二进制模式打开output_path
    with open(output_path, "wb") as output_file:
        # 将merger写入output_file
        merger.write(output_file)

    # 关闭merger
    merger.close()

    # 打印合并后的pdf文件路径
    print(f"Merged PDF file: {output_path}")


def is_image(file_path):
    try:
        Image.open(file_path)
        return True
    except IOError:
        return False


async def main():
    #从文件中读取一个嵌套json结构，其中包含一个名为"DownloadSrcInfro"的列表，列表中的每个元素都包含一个名为"downloadUrl"的属性
    data_str = None
    with open(".\downloadsource.json", "r", encoding="utf-8") as f:
        data= json.load(f)
        
    # 获取PdfRootPath
    pdf_root_path = data["PdfSaveRootPath"]

    # 遍历data对象的documents列表，获取downloadUrl属性
    for document_item in data["DownloadSrcs"]:
        if document_item.get("downloadUrl"):
            # 判断isDownloaded属性是否为True，如果为True，则跳过
            if document_item.get("isDownloaded", False):
                continue

            save_dir, pdf_file_name = await download_images(
                document_item["downloadUrl"], pdf_root_path, document_item["imgClasses"]
            )

            # 遍历文件夹save_dir中的所有文件，按文件名升序排序后，将图片转换为pdf，并保存到源文件所在目录下的临时pdf文件夹下
            pdf_paths = []
            for image_path in sorted(os.listdir(save_dir)):
                # 拼接图片路径和文件名
                image_path = os.path.normpath(os.path.join(save_dir, image_path))
                if is_image(image_path):
                    # 拼接pdf保存路径和文件名
                    filename, extension = os.path.splitext(os.path.basename(image_path))
                    pdf_path = os.path.normpath(
                        os.path.join(save_dir, f"{filename}.pdf")
                    )

                    # 转换图片为pdf
                    if not os.path.exists(pdf_path):
                        convert_image_to_pdf(image_path, pdf_path)
                        # 保存pdf路径到列表中
                        pdf_paths.append(pdf_path)
                    else:
                        print(f"PDF file {pdf_path} already exists.")

                    # 删除图片文件和临时pdf文件
                    os.remove(image_path)

            # 合并pdf文件
            pdf_full_path = os.path.normpath(
                os.path.join(save_dir, f"{pdf_file_name}.pdf")
            )
            sorted_pdf_paths = sorted(
                pdf_paths, key=lambda x: int(os.path.splitext(os.path.basename(x))[0])
            )
            merge_pdfs(sorted_pdf_paths, pdf_full_path)

            # 更新downloadUrl的json对象的isDownloaded属性为True，pdfSavePath属性为PDF文件的绝对路径
            document_item.update({"isDownloaded": True, "pdfSavePath": pdf_full_path})

    # 保存更新后的data对象到文件夹downloadsource.json
    with open("downloadsource.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    asyncio.run(main())
