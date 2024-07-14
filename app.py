import logging
import logging.handlers
import os
import pathlib
import pytz
from telegram.ext import (
    Application,
    Defaults,
    JobQueue,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler
)

from menupage import MenuPattern
from model import CCT, CT
from service import BugSignalService


# TODO local logger configuration file
config = {
    'logger': {
        'filename': 'logs/bugsignal.log',
        'maxBytes': 1024 * 1024 * 5,
        'level': 'DEBUG',
    },
    # 'timezone': 'Europe/Moscow',
}



if __name__ == '__main__':
    # prepare and start logger
    pathlib.Path(config['logger']['filename']).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(config['logger']['filename'],
                                                   mode=config['logger'].get('mode', 'a'),
                                                   maxBytes=config['logger'].get('maxBytes', 1024 * 1024 * 5),
                                                   backupCount=config['logger'].get('backupCount', 3),
                                                   encoding=config['logger'].get('encoding', 'utf-8'),
                                                   delay=config['logger'].get('delay', False),
                                                   errors=config['logger'].get('errors'),
                                                   )
    logging.basicConfig(handlers=[handler],
                        level=config['logger']['level'],
                        format='[%(asctime)s] [%(levelname)s] %(message)s',
                        # datefmt='%Y-%m-%d %H:%M:%S',
                        )
    logger = logging.getLogger('bugSignal_Logger')
    logger.info('Logger initialized')
    # create application
    bot = BugSignalService(logger)
    job_queue = JobQueue[CCT]()
    application = (Application.builder()
                   .context_types(CT)
                   .job_queue(job_queue)
                   .token(os.environ['BUGSIGNAL_TELEGRAM_TOKEN'])
                # .read_timeout(bot.cf.READ_TIMEOUT)
                # .write_timeout(bot.cf.WRITE_TIMEOUT)
                # .connect_timeout(bot.cf.CONNECT_TIMEOUT)
                # .pool_timeout(bot.cf.POOL_TIMEOUT)
                   .defaults(Defaults(tzinfo=pytz.UTC))
                   .build())
    assert application.job_queue is not None, f"Cannot initialize job queue"
    # add handlers
    application.add_handler(CommandHandler('start', bot.start))
    application.add_handler(CommandHandler('fox', bot.fox))
    application.add_handler(CommandHandler('zombie', bot.zombie))
    application.add_handler(CommandHandler('menu', bot.main_menu))
    application.add_handler(CallbackQueryHandler(bot.main_menu, MenuPattern.MAIN))
    application.add_handler(CallbackQueryHandler(bot.listeners_menu, MenuPattern.LISTENERS))
    application.add_handler(CallbackQueryHandler(bot.chats_menu, MenuPattern.CHATS))
    application.add_handler(CallbackQueryHandler(bot.subscriptions_menu, MenuPattern.SUBSCRIPTIONS))
    application.add_handler(CallbackQueryHandler(bot.roles_menu, MenuPattern.ROLES))

    # add message handlers: Group policy Off required
    # application.add_handler(MessageHandler(None, bot.message))
    # error handler
    application.add_error_handler(bot._onerror)

    with bot.run() as service:
        application.run_polling()
        ...
    logger.info('Application closed')
    for handler in logger.handlers:
        logger.removeHandler(handler)


