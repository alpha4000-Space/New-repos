import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import router
from exchange_handlers import exchange_router
from admin_config import admin_config_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def rates_updater():
    """Har 30 daqiqada kurslarni yangilaydi"""
    from rates_api import update_live_rates
    while True:
        try:
            await update_live_rates()
            log.info("Kurslar avtomatik yangilandi")
        except Exception as e:
            log.warning(f"Kurs yangilanmadi: {e}")
        await asyncio.sleep(30 * 60)   # 30 daqiqa


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin_config_router)
    dp.include_router(exchange_router)
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        from rates_api import update_live_rates
        await update_live_rates()
        log.info("Boshlang'ich kurslar yuklandi")
    except Exception as e:
        log.warning(f"Boshlang'ich kurs yuklanmadi: {e}")

    asyncio.create_task(rates_updater())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())