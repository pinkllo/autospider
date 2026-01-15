# 登录配置 - 多账号列表
ACCOUNTS = [
    # {"username": "13798252655", "password": "Erp123456"},
     {"username": "13822786191", "password": "Erp123456"},
     {"username": "13631180662", "password": "Erp123456"},
    #{"username": "13710862513", "password": "Aa123456.."}
]

# 基础 URL
BASE_URL = "https://uat-publish.nfcb.com.cn/oauth/login"

# 登录提交按钮
LOGIN_BUTTON_XPATH = '//*[@id="btn-login"]'

# 菜单导航三级路径
MENU_LEVEL_1 = "//span[contains(@class, 'tree-title') and text()='编务管理']"
MENU_LEVEL_2 = "//span[contains(@class, 'tree-title') and text()='日常业务']"
MENU_LEVEL_3 = "//span[contains(@class, 'tree-title') and text()='书号和CIP发放']"

# 详情页与列表操作 (增强通用性)
# 优先级：表格第一行链接 > onclick为详情的链接 > 包含特定字段内容的链接
DETAIL_LINK_XPATH = '/html/body/div[1]/div/div/div[2]/div[3]/div[2]/table/tbody/tr/td[3]/div/div/a[1]'

# 翻页按钮 (用户提供)
NEXT_PAGE_XPATH = '//*[@id="layui-laypage-4"]/a[@class="layui-laypage-next"] | //a[contains(@class, "layui-laypage-next")]'

TAB_3_XPATH = '//*[@id="LAY_app_tabsheader"]/li[3]'
LIST_TAB_XPATH = '//*[@id="LAY_app_tabsheader"]/li[2]'
# 数据库配置 (MySQL)
DB_CONFIG = {
    'host': '122.112.245.131',
    'user': 'intern',
    'password': 'SLxI4SSQpO#M7ff',
    'database': 'data_set_test',
    'charset': 'utf8mb4'
}
TABLE_NAME = "webspider_book_execl_isbn_cip"

# 列名中英文映射
COLUMN_MAPPING = {
    "制单机构": "organization",
    "业务日期": "business_date",
    "申请单号": "application_no",
    "物品档案": "item_record",
    "物品类型": "item_type",
    "财务分类": "financial_category",
    "丛书名": "series_name",
    "选题申报单号": "topic_apply_no",
    "业务部门": "department",
    "责任编辑": "editor",
    "中图分类": "clc_category",
    "书号": "isbn",
    "条形码": "barcode",
    "印次": "print_times",
    "CIP分类": "cip_category",
    "出版类别": "publication_category",
    "选题号": "topic_no",
    "备注": "remarks",
    "remarks": "remarks",
    "CIP信息": "cip_info",
    "cipInfo": "cip_info",
    "附加码": "additional_code",
    "外文书名": "foreign_title",
    "账号": "account"
}
