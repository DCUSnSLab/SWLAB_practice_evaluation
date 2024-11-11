import os
import subprocess
import tkinter as tk
from tkinter import filedialog, ttk


class CFileBuilderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("C File Builder")
        self.root.geometry("800x600")

        # 메인 프레임을 세로로 나눔
        self.main_frame = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 왼쪽: 파일 트리 구조 및 인자 입력
        self.tree_frame = tk.Frame(self.main_frame)
        self.main_frame.add(self.tree_frame)

        # Select Directory 버튼과 인자 입력 필드
        self.top_frame = tk.Frame(self.tree_frame)
        self.top_frame.pack(fill=tk.X)

        self.select_button = tk.Button(self.top_frame, text="Select Directory", command=self.select_directory)
        self.select_button.pack(side=tk.LEFT, padx=5, pady=10)

        self.args_label = tk.Label(self.top_frame, text="Args:")
        self.args_label.pack(side=tk.LEFT, padx=5)

        self.args_entry = tk.Entry(self.top_frame, width=30)
        self.args_entry.pack(side=tk.LEFT, padx=5)

        # Run Executable 버튼 추가
        self.run_button = tk.Button(self.top_frame, text="Run Executable", command=self.run_executable)
        self.run_button.pack(side=tk.LEFT, padx=5)

        # 트리 구조 표시
        self.tree = ttk.Treeview(self.tree_frame)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # 오른쪽: 빌드 및 실행 결과 출력
        self.result_frame = tk.Frame(self.main_frame)
        self.main_frame.add(self.result_frame)

        self.result_text = tk.Text(self.result_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # 현재 선택된 파일 경로 저장 변수
        self.selected_file = None

    def select_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.tree.delete(*self.tree.get_children())  # 기존 트리 초기화
            self.populate_tree(directory)

    def populate_tree(self, directory, parent=""):
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                node_id = self.tree.insert(parent, "end", text=item, open=False)
                self.populate_tree(item_path, node_id)
            elif item.endswith(".c"):
                self.tree.insert(parent, "end", text=item, values=(item_path,))
                executable_path = os.path.splitext(item_path)[0]
                if os.path.exists(executable_path):
                    self.tree.insert(parent, "end", text=os.path.basename(executable_path), values=(executable_path,))

    def on_tree_select(self, event):
        # 일반 클릭으로 파일 선택
        selected_item = self.tree.selection()
        if not selected_item:
            return

        file_path = self.tree.item(selected_item[0], "values")
        if file_path:
            self.selected_file = file_path[0]

    def on_tree_double_click(self, event):
        # 더블 클릭으로 파일 실행
        self.on_tree_select(event)  # 파일 선택 업데이트
        if self.selected_file:
            self.run_executable()

    def build_and_run(self, c_file):
        executable_name = os.path.splitext(os.path.basename(c_file))[0]
        output_path = os.path.join(os.path.dirname(c_file), executable_name)
        error_log_file = os.path.join(os.path.dirname(c_file), f"error_{executable_name}.log")

        command = ["gcc", c_file, "-o", output_path]
        try:
            subprocess.run(command, check=True, stderr=subprocess.PIPE)
            result_message = f"Successfully built {c_file} -> {output_path}\n\n"

            if os.path.exists(error_log_file):
                os.remove(error_log_file)

            self.selected_file = output_path
        except subprocess.CalledProcessError as e:
            with open(error_log_file, "w") as log_file:
                log_file.write(e.stderr.decode("utf-8"))
            result_message = f"Failed to build {c_file}. Error log saved to {error_log_file}\n\n" + e.stderr.decode(
                "utf-8")

        self.update_result_text(result_message)

    def run_executable(self):
        if not self.selected_file:
            self.update_result_text("No file selected. Please select a .c file or executable first.")
            return

        if not os.path.exists(self.selected_file):
            self.update_result_text(f"Executable not found: {self.selected_file}")
            return

        args = self.args_entry.get().strip().split()

        try:
            execution_result = subprocess.run([self.selected_file] + args, check=True, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE)
            result_message = "Execution Output:\n" + execution_result.stdout.decode("utf-8")
        except subprocess.CalledProcessError as e:
            result_message = f"Execution failed:\n{e.stderr.decode('utf-8')}"

        self.update_result_text(result_message)

    def update_result_text(self, message):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, message)
        self.result_text.config(state=tk.DISABLED)


# 애플리케이션 실행
root = tk.Tk()
app = CFileBuilderApp(root)
root.mainloop()
