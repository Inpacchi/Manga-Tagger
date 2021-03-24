import requests
import os
import zipfile
import xml.etree.ElementTree as ET
import re
from PIL import Image
import pymanga
from bs4 import BeautifulSoup


def flat(*nums):
    'Build a tuple of ints from float or integer arguments. Useful because PIL crop and resize require integer points.'

    return tuple(int(round(n)) for n in nums)


class Size(object):
    def __init__(self, pair):
        self.width = float(pair[0])
        self.height = float(pair[1])

    @property
    def aspect_ratio(self):
        return self.width / self.height

    @property
    def size(self):
        return flat(self.width, self.height)


def cropped_thumbnail(img, size):
    '''
    Builds a thumbnail by cropping out a maximal region from the center of the original with
    the same aspect ratio as the target size, and then resizing. The result is a thumbnail which is
    always EXACTLY the requested size and with no aspect ratio distortion (although two edges, either
    top/bottom or left/right depending whether the image is too tall or too wide, may be trimmed off.)
    '''

    original = Size(img.size)
    target = Size(size)

    if target.aspect_ratio > original.aspect_ratio:
        # image is too tall: take some off the top and bottom
        scale_factor = target.width / original.width
        crop_size = Size((original.width, target.height / scale_factor))
        top_cut_line = (original.height - crop_size.height) / 2
        img = img.crop(flat(0, top_cut_line, crop_size.width, top_cut_line + crop_size.height))
    elif target.aspect_ratio < original.aspect_ratio:
        # image is too wide: take some off the sides
        scale_factor = target.height / original.height
        crop_size = Size((target.width / scale_factor, original.height))
        side_cut_line = (original.width - crop_size.width) / 2
        img = img.crop(flat(side_cut_line, 0, side_cut_line + crop_size.width, crop_size.height))

    return img.resize(target.size, Image.ANTIALIAS)

def thumb(dir):
    if "default.jpg" not in os.listdir(dir) and os.listdir(dir):
        file = [x for x in os.listdir(dir) if x.endswith('.cbz')][0]
        with zipfile.ZipFile(os.path.join(dir, file)) as z:
            if "ComicInfo.xml" in os.listdir(dir):
                os.remove(os.path.join(dir, "ComicInfo.xml"))
            #print(z.namelist())
            info = z.extract(z.getinfo("ComicInfo.xml"), dir)
            z.close()
            tree = ET.parse(os.path.join(dir, "ComicInfo.xml"))
            root = tree.getroot()
            webUrl = root.findall("Web")[0].text
            image = None
            if "myanimelist" in webUrl:
                webUrl = re.search('(?<=manga/)\d+', webUrl)
                # r = requests.get("https://api.jikan.moe/v3/manga/" + webUrl.group(0) + "/pictures")
                r = requests.get("https://api.jikan.moe/v3/manga/" + webUrl.group(0))
                json = r.json()
                #print(json["image_url"].replace(".jpg", "l.jpg"))
                image = requests.get(json["image_url"].replace(".jpg", "l.jpg"), stream=True)
            elif "anilist" in webUrl:
                req = requests.get(webUrl)
                soup = BeautifulSoup(req.content, 'html.parser')
                image = requests.get(soup.find_all(name="img")[0]["src"], stream=True)
            elif "mangaupdates" in webUrl:
                webUrl = pymanga.series(re.search('(?<=\?id=/)\d+', webUrl))["image"]
                image = image.requests.get(webUrl, stream=True)
            else:
                with zipfile.ZipFile(os.path.join(dir, file)) as z:
                    imagefile = next(file for file in z.namelist() if (file.endswith(".png") or file.endswith(".jpg") or file.endswith(".jpeg") or file.endswith(".webp")))
                    imagefile = z.extract(imagefile)
                    image = Image.open(imagefile)
                    if image.mode is "RGBA":
                        new_image = Image.new("RGBA", image.size, "WHITE")
                        new_image.paste(image, (0, 0), image)
                        new_image = new_image.convert('RGB')
                    else:
                        new_image = Image.new("RGB", image.size)
                        new_image.paste(image, (0, 0))
                    width = new_image.size[0]
                    height = new_image.size[1]

                    aspect = width / float(height)

                    ideal_width = 150
                    ideal_height = 212

                    ideal_aspect = ideal_width / float(ideal_height)

                    if aspect > ideal_aspect:
                        # Then crop the left and right edges:
                        new_width = int(ideal_aspect * height)
                        offset = (width - new_width) / 2
                        resize = (offset, 0, width - offset, height)
                    else:
                        # ... crop the top and bottom:
                        new_height = int(width / ideal_aspect)
                        offset = (height - new_height) / 2
                        resize = (0, offset, width, height - offset)

                    new_image = new_image.crop(resize)
                    new_image.save(os.path.join(dir, "default.jpg"), "JPEG", quality=100)
                    os.remove(info)
                    return
            img = Image.open(image.raw)
            width = img.size[0]
            height = img.size[1]

            aspect = width / float(height)

            ideal_width = 150
            ideal_height = 212

            ideal_aspect = ideal_width / float(ideal_height)

            if aspect > ideal_aspect:
                # Then crop the left and right edges:
                new_width = int(ideal_aspect * height)
                offset = (width - new_width) / 2
                resize = (offset, 0, width - offset, height)
            else:
                # ... crop the top and bottom:
                new_height = int(width / ideal_aspect)
                offset = (height - new_height) / 2
                resize = (0, offset, width, height - offset)

            img = img.crop(resize)
            img.save(os.path.join(dir, "default.jpg"))
            img.close()
            os.remove(info)
