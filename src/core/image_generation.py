from PIL import Image

from aiogram.enums import InputMediaType
from aiogram.types import InputMediaPhoto

from src.utils.analytics.logging import logged
from src.utils.globals import openai_client


async def generate_image(prompt):
    response = await openai_client.images.generate(
        prompt=prompt,
        n=1,
        size="1024x1024",
        quality="standard",
        style="vivid",
        model="dall-e-3",
    )
    return response.data[0].url


@logged
async def variate_image(path_to_image):
    img = Image.open(f"{path_to_image}.jpg")
    img.save(f"{path_to_image}.png")
    response = await openai_client.images.create_variation(
        image=open(f"{path_to_image}.png", "rb"),
        n=2,
        size="1024x1024",
        model="dall-e-2",
    )
    media = [
        InputMediaPhoto(type=InputMediaType.PHOTO, media=response.data[0].url),
        InputMediaPhoto(type=InputMediaType.PHOTO, media=response.data[1].url),
    ]
    return media
