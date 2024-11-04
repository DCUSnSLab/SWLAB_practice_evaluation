import os
import subprocess

def find_c_files(directory):
    c_files = []

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".c"):
                c_files.append(os.path.join(root, file))

    return c_files


def build_c_files(c_files):
    for c_file in c_files:
        # .c 파일 이름을 추출하고 확장자 제거
        executable_name = os.path.splitext(os.path.basename(c_file))[0]
        output_path = os.path.join(os.path.dirname(c_file), executable_name)

        # 오류 로그 파일 경로 설정
        error_log_file = os.path.join(os.path.dirname(c_file), f"error_{executable_name}.log")

        # gcc 명령어 실행
        command = ["gcc", c_file, "-o", output_path]
        try:
            subprocess.run(command, check=True, stderr=subprocess.PIPE)
            print(f"Successfully built {c_file} -> {output_path}")

            # 빌드 성공 시 기존 오류 로그 파일이 있으면 삭제
            if os.path.exists(error_log_file):
                os.remove(error_log_file)
        except subprocess.CalledProcessError as e:
            # 빌드 실패 시 오류 로그 파일 생성
            with open(error_log_file, "w") as log_file:
                log_file.write(e.stderr.decode("utf-8"))
            print(f"Failed to build {c_file}. Error log saved to {error_log_file}")

directory = "/home/ros/PycharmProjects/SWLAB_practice_evaluation/src/origin/system_0_2024"
c_files = find_c_files(directory)

# 결과 출력
c_files = find_c_files(directory)
build_c_files(c_files)