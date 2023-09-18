import logging

#logging.basicConfig(level=logging.INFO)
# log 생성
logger = logging.getLogger(__name__)

# log 출력 기준 설정
logger.setLevel(logging.DEBUG)

# log 출력 형식
formatter = logging.Formatter(u'%(asctime)s [%(levelname)s] [%(name)s] %(message)s')

# log 출력
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# log 파일에 출력
# file_handler = logging.FileHandler('./myLog.log')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)
