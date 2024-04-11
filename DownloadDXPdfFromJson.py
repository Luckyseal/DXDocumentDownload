import os
from bs4 import BeautifulSoup
from PyPDF2 import PdfMerger, PdfReader
from PIL import Image
import json
from urllib.parse import parse_qs, urlparse
import asyncio
import aiohttp
import multiprocessing
import unicodedata

import re
import unicodedata
import tempfile

def sanitize_filename(filename, replace_with="_", max_length=255):
    """
    将无效的Windows文件名字符替换为有效字符,支持中文和英文。
    :param filename: 原始文件名
    :param replace_with: 用于替换无效字符的字符
    :param max_length: 文件名的最大长度
    :return: 符合Windows文件名规范的新文件名
    """
    try:
        # 删除文件名中的无效字符
        invalid_chars_regex = r'[\\/:*?"<>|]'
        cleaned_filename = re.sub(invalid_chars_regex, replace_with, unicodedata.normalize('NFKD', filename))

        # 删除文件名中的保留字符
        reserved_names = ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(10)] + [f"LPT{i}" for i in range(10)]
        #reserved_regex = r'^(?i)(' + '|'.join(reserved_names) + r')\.?'
        if cleaned_filename.upper() in reserved_names:
            raise ValueError(f"文件名不能使用保留字: {cleaned_filename}")

        # 删除文件名前后的空格和点号
        cleaned_filename = cleaned_filename.strip(" .")
        # 将连续的点号替换为单个点号
        cleaned_filename = re.sub(r"\.+", ".", cleaned_filename)

        # 限制文件名长度
        if len(cleaned_filename) > max_length:
            cleaned_filename = cleaned_filename[:max_length]

        # 如果文件名为空,返回默认名称
        if not cleaned_filename:
            cleaned_filename = "default_filename"

        return cleaned_filename
    except Exception as e:
        print(f"Error occurred while sanitizing filename: {e}")
        return filename

async def download_image(session, img_url, file_name):
    '''
    Download an image from a given URL and save it to a file with a given name.'''
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
                folder_name = sanitize_filename(folder_name.text.strip().replace("\\n", ""))
            else:
                print(f"Unable to find folder name in URL: {url}")
                return None, None

            save_dir = os.path.join(save_root_path, folder_name)
            os.makedirs(save_dir, exist_ok=True)

            img_tags = soup.find_all("img", class_=img_classes)

            async def download_image_task(img_url, img_name):
                async with session.get(img_url) as response:
                    if response.status == 200:
                        img_data = await response.read()
                        with open(img_name, "wb") as f:
                            f.write(img_data)
                        print(f"Downloaded image: {img_name}")
                    else:
                        print(f"Failed to download image: {img_url}")

            async def generate_tasks():
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

                    yield download_image_task(img_url, img_name)

            tasks = []
            async for task in generate_tasks():
                tasks.append(task)

            await asyncio.gather(*tasks)

        return save_dir, folder_name
    except Exception as e:
        print(f"Error occurred while downloading images: {e}")
        return None, None

def convert_image_to_pdf(image_path, pdf_path):
    '''
    Convert an image to a PDF file.
    :param image_path: The path to the image file.
    :param pdf_path: The path to the output PDF file.
    :return: None
    '''
    image = Image.open(image_path)
    image.save(pdf_path, "PDF", resolution=100.0)

def merge_pdfs_worker(pdf_paths, output_path):
    '''
    Merge a list of PDF files into a single PDF file.
    :param pdf_paths: A list of paths to the PDF files to be merged.
    :param output_path: The path to the output PDF file.
    :return: None
    '''
    merger = PdfMerger()

    for pdf_path in pdf_paths:
        with open(pdf_path, "rb") as file:
            pdf_reader = PdfReader(file)
            merger.append(pdf_reader)

    with open(output_path, "wb") as output_file:
        merger.write(output_file)

    print(f"Merged PDF file: {output_path}")

import tempfile

def merge_pdfs(pdf_paths, output_path, num_processes=4):
    if not pdf_paths:
        raise ValueError("pdf_paths cannot be empty")

    chunk_size = (len(pdf_paths) + num_processes - 1) // num_processes
    chunks = [pdf_paths[i:i+chunk_size] for i in range(0, len(pdf_paths), chunk_size)]

    processes = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for i, chunk in enumerate(chunks):
            output_chunk_path = os.path.join(temp_dir, f"part{i}.pdf")
            p = multiprocessing.Process(target=merge_pdfs_worker, args=(chunk, output_chunk_path))
            processes.append(p)
            p.start()

        for p in processes:
            p.join()

        merger = PdfMerger()
        for i in range(len(chunks)):
            part_path = os.path.join(temp_dir, f"part{i}.pdf")
            with open(part_path, "rb") as file:
                pdf_reader = PdfReader(file)
                merger.append(pdf_reader)

        with open(output_path, "wb") as output_file:
            merger.write(output_file)

        print(f"Merged PDF file: {output_path}")

def is_image(file_path):
    try:
        Image.open(file_path)
        return True
    except IOError:
        return False

async def main():
    data = None
    with open("downloadsource.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    pdf_root_path = data["PdfSaveRootPath"]

    for document_item in data["DownloadSrcs"]:
        if document_item.get("downloadUrl"):
            if document_item.get("isDownloaded", False):
                continue

            save_dir, pdf_file_name = await download_images(
                document_item["downloadUrl"], pdf_root_path, document_item["imgClasses"]
            )

            if save_dir is None:
                continue

            pdf_paths = []
            for image_path in sorted(os.listdir(save_dir)):
                image_path = os.path.normpath(os.path.join(save_dir, image_path))
                if is_image(image_path):
                    filename, extension = os.path.splitext(os.path.basename(image_path))
                    pdf_path = os.path.normpath(os.path.join(save_dir, f"{filename}.pdf"))

                    if not os.path.exists(pdf_path):
                        convert_image_to_pdf(image_path, pdf_path)
                    else:
                        print(f"PDF file {pdf_path} already exists.")

                    pdf_paths.append(pdf_path)
                    os.remove(image_path)

            pdf_full_path = os.path.normpath(os.path.join(save_dir, f"{pdf_file_name}.pdf"))
            sorted_pdf_paths = sorted(pdf_paths, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
            merge_pdfs(sorted_pdf_paths, pdf_full_path)

            document_item.update({"isDownloaded": True, "pdfSavePath": pdf_full_path})

    with open("downloadsource.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    asyncio.run(main())
