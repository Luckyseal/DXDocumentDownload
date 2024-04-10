import os
import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfFileMerger, PdfFileReader
from PIL import Image
import json
from urllib.parse import parse_qs, urlparse
import asyncio
import aiohttp

async def download_image(session, img_url, file_name):
    async with session.get(img_url) as response:
        if response.status == 200:
            img_data = await response.read()
            with open(file_name, "wb") as f:
                f.write(img_data)
            print(f"Downloaded image: {file_name}")
        else:
            print(f"Failed to download image: {img_url}")

async def download_images(url, save_root_path, img_classes):
    async with aiohttp.ClientSession() as session:
        # 发送HTTP请求，获取网页内容
        async with session.get(url) as response:
            response_text = await response.text()

        # 使用BeautifulSoup解析网页内容
        soup = BeautifulSoup(response_text, "html.parser")

        # 查找网页中 class 为rich_media_title 的<h1>标签 获取标签内容作为保存图片的文件夹名
        folder_name = soup.find("h1", class_="rich_media_title").text.strip().replace('\\n', '')
        # 拼接保存图片的文件夹路径
        save_dir = os.path.join(save_root_path, folder_name)
        # 创建保存图片的文件夹
        os.makedirs(save_dir, exist_ok=True)

        # 查找网页中的所有 class 为rich_pages wxw-img的<img>标签
        img_tags = soup.find_all("img", class_=img_classes)

        # 使用异步方式下载图片
        tasks = []
        for i, img_tag in enumerate(img_tags, start=1):
            if int(img_tag.get('data-w', 0)) < 1080:
                continue

            img_url = img_tag.get('data-src')
            # img_url为空跳过
            if not img_url:
                continue

            # 解析img_url,获取URL参数的值。
            parsed_url = urlparse(img_url)
            query_params = parse_qs(parsed_url.query)

            # 从原始URL参数wx_fmt获取文件格式
            wx_fmt = query_params.get('wx_fmt')
            img_name = os.path.join(save_dir, f"{i}.{wx_fmt}")

            # 避免重复下载
            if os.path.exists(img_name):
                print(f"Image {img_name} already exists.")
                continue

            task = asyncio.create_task(download_image(session, img_url, img_name))
            tasks.append(task)

        await asyncio.gather(*tasks)

    return save_dir, folder_name

def convert_image_to_pdf(image_path, pdf_path):
    image = Image.open(image_path)
    image.save(pdf_path, "PDF", resolution=100.0)

def merge_pdfs(pdf_paths, output_path):
    merger = PdfFileMerger()
    for pdf_path in pdf_paths:
        with open(pdf_path, "rb") as file:
            pdf_reader = PdfFileReader(file)
            merger.append(pdf_reader)

    with open(output_path, "wb") as output_file:
        merger.write(output_file)

def is_image(file_path):
    try:
        Image.open(file_path)
        return True
    except IOError:
        return False

async def main():
    # 读取文件夹downloadsource.json文件内容，下载download_url网页的图片，并保存到源文件所在目录下的images文件夹
    with open("downloadsource.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # 遍历data对象，获取downloadUrl属性
    for document_item in data:
        if document_item["downloadUrl"]:
            # 判断isDownloaded属性是否为True，如果为True，则跳过
            if document_item["isDownloaded"]:
                continue

            save_dir, pdf_file_name = await download_images(document_item["downloadUrl"], "./", document_item["imgClasses"])

            # 遍历文件夹save_dir中的所有文件，按文件名升序排序后，将图片转换为pdf，并保存到源文件所在目录下的临时pdf文件夹下
            pdf_paths = []
            for image_path in sorted(os.listdir(save_dir)):
                # 拼接图片路径和文件名
                image_path = os.path.normpath(os.path.join(save_dir, image_path))
                if is_image(image_path):
                    # 拼接pdf保存路径和文件名
                    filename, extension = os.path.splitext(os.path.basename(image_path))
                    pdf_path = os.path.normpath(os.path.join(save_dir, f"{filename}.pdf"))

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
            pdf_full_path = os.path.normpath(os.path.join(save_dir, f"{pdf_file_name}.pdf"))
            sorted_pdf_paths = sorted(pdf_paths, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
            merge_pdfs(sorted_pdf_paths, pdf_full_path)

            # 更新downloadUrl的json对象的isDownloaded属性为True，pdfSavePath属性为PDF文件的绝对路径
            document_item.update({"isDownloaded": True, "pdfSavePath": pdf_full_path})

    # 保存更新后的data对象到文件夹downloadsource.json
    with open("downloadsource.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    asyncio.run(main())