import os
from DrissionPage import Chromium, ChromiumOptions
import PathHelper

current_path = PathHelper.get_working_dir()
edge_data_folder = os.path.join(current_path, 'Edge\\Data')

def is_initialized():
    return os.path.exists(edge_data_folder)

def create(port=9213) -> Chromium:

    browser_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    # noinspection PyTypeChecker
    options = ChromiumOptions(read_file=False)
    # options.headless(headless)
    options.set_browser_path(browser_path)
    options.set_local_port(port)
    options.set_user_data_path(edge_data_folder)
    options.set_user('MyProfile')
    options.set_argument('--language', 'zh_cn')
    options.set_argument('--disable-extensions')
    options.set_argument('--disable-background-networking')

    return Chromium(addr_or_opts=options)
