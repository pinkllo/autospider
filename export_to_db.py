import pandas as pd
from sqlalchemy import create_engine, text
import config
import os
from datetime import datetime

def export_excel_to_db(file_paths):
    """将多个 Excel 文件合并并写入远程 MySQL 数据库"""
    if not file_paths:
        print("未提供文件路径")
        return

    all_dfs = []
    
    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"文件不存在: {file_path}")
            continue
            
        print(f"正在读取: {file_path}")
        try:
            df = pd.read_excel(file_path)
            
            # 从文件名提取账号 (例如: 13631180662_20260113_123012.xlsx -> 13631180662)
            filename = os.path.basename(file_path)
            account = filename.split('_')[0]
            
            # 确保账号列存在且在第一列
            if '账号' in df.columns:
                # 如果已存在，先删除再插入到第一列，确保顺序和内容正确
                cols = list(df.columns)
                cols.remove('账号')
                df = df[cols]
            
            df.insert(0, '账号', account)
            
            all_dfs.append(df)
            print(f"已加载 {len(df)} 条数据，账号: {account}")
        except Exception as e:
            print(f"读取文件 {file_path} 时出错: {e}")

    if not all_dfs:
        print("没有可导入的数据")
        return

    # 合并数据框
    print("\n正在合并并处理列名...")
    combined_df = pd.concat(all_dfs, ignore_index=True)
    
    # 根据 config 中的映射进行重命名
    combined_df = combined_df.rename(columns=config.COLUMN_MAPPING)
    
    # 去除列名中可能存在的首尾空格
    combined_df.columns = [c.strip() for c in combined_df.columns]
    
    # 构建 SQLAlchemy 引擎
    c = config.DB_CONFIG
    conn_str = f"mysql+pymysql://{c['user']}:{c['password']}@{c['host']}/{c['database']}?charset={c['charset']}"
    
    print(f"正在连接远程数据库 {c['host']}...")
    try:
        engine = create_engine(conn_str)
        # 写入数据库
        combined_df.to_sql(config.TABLE_NAME, engine, if_exists='replace', index=False)
        print(f"✅ 成功将 {len(combined_df)} 条数据导入到远程表 '{config.TABLE_NAME}'")
        
        # 为字段添加备注 (MySQL 专用)
        print("正在为数据库字段添加中文备注...")
        with engine.connect() as connection:
            reverse_mapping = {v: k for k, v in config.COLUMN_MAPPING.items()}
            
            for eng_col in combined_df.columns:
                chn_label = reverse_mapping.get(eng_col)
                if chn_label:
                    try:
                        # 批量修改列备注。
                        # 注意：MySQL MODIFY 改备注必须带上数据类型。
                        # Pandas 默认对字符串生成的通常是 LONGTEXT 或 TEXT。
                        sql = f"ALTER TABLE `{config.TABLE_NAME}` MODIFY COLUMN `{eng_col}` LONGTEXT COMMENT :remark"
                        connection.execute(text(sql), {"remark": chn_label})
                    except Exception as e_col:
                        print(f"为字段 {eng_col} ({chn_label}) 添加备注失败: {e_col}")
            connection.commit()
        print("✅ 字段备注添加完成")
        
    except Exception as e:
        print(f"操作远程数据库时出错: {e}")

if __name__ == "__main__":
    files_to_import = [
        r"output\13631180662_20260113_123012.xlsx", 
        r"output\13710862513_20260113_220601.xlsx",
        r"output\13822786191_20260113_122927.xlsx"
    ]
    
    export_excel_to_db(files_to_import)
