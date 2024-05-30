import requests
from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
import re
import time
import sqlite3
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter


def scrape_real_estate_data(base_url, max_page):
    """
    base_url (str): スクレイピングの基本となるURL
    max_page (int): スクレイピングする最大ページ数
    """
    all_data  = []

    for page in range(1, max_page + 1):
        url = base_url.format(page)
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'lxml')
        items = soup.findAll("div", {"class": "cassetteitem"})

        print("page", page, "items", len(items))

        for item in items:
            base_data = {}
            base_data["名称"]     = item.find("div", {"class": "cassetteitem_content-title"}).get_text(strip=True) if item.find("div", {"class": "cassetteitem_content-title"}) else None
            base_data["カテゴリ"] = item.find("div", {"class": "cassetteitem_content-label"}).span.get_text(strip=True) if item.find("div", {"class": "cassetteitem_content-label"}) else None
            base_data["アドレス"] = item.find("li", {"class": "cassetteitem_detail-col1"}).get_text(strip=True) if item.find("li", {"class": "cassetteitem_detail-col1"}) else None

            # 駅のアクセス情報をまとめて取得
            base_data["アクセス"] = ", ".join([station.get_text(strip=True) for station in item.findAll("div", {"class": "cassetteitem_detail-text"})])

            construction_info = item.find("li", {"class": "cassetteitem_detail-col3"}).find_all("div") if item.find("li", {"class": "cassetteitem_detail-col3"}) else None
            base_data["築年数"] = construction_info[0].get_text(strip=True) if construction_info and len(construction_info) > 0 else None
            base_data["構造"] = construction_info[1].get_text(strip=True) if construction_info and len(construction_info) > 1 else None

            tbodys = item.find("table", {"class": "cassetteitem_other"}).findAll("tbody")


            for tbody in tbodys:
                data = base_data.copy()
                # 階数情報の正確な取得
                floor_info = tbody.find_all("td")[2].get_text(strip=True) if len(tbody.find_all("td")) > 2 else None
                data["階数"]   = floor_info
                data["家賃"]   = tbody.select_one(".cassetteitem_price--rent").get_text(strip=True) if tbody.select_one(".cassetteitem_price--rent") else None
                data["管理費"] = tbody.select_one(".cassetteitem_price--administration").get_text(strip=True) if tbody.select_one(".cassetteitem_price--administration") else None
                data["敷金"]   = tbody.select_one(".cassetteitem_price--deposit").get_text(strip=True) if tbody.select_one(".cassetteitem_price--deposit") else None
                data["礼金"]   = tbody.select_one(".cassetteitem_price--gratuity").get_text(strip=True) if tbody.select_one(".cassetteitem_price--gratuity") else None
                data["間取り"] = tbody.select_one(".cassetteitem_madori").get_text(strip=True) if tbody.select_one(".cassetteitem_madori") else None
                data["面積"]   = tbody.select_one(".cassetteitem_menseki").get_text(strip=True) if tbody.select_one(".cassetteitem_menseki") else None

                # 物件画像・間取り画像・詳細URLの取得を最後に行う
                property_image_element = item.find(class_="cassetteitem_object-item")
                data["物件画像URL"] = property_image_element.img["rel"] if property_image_element and property_image_element.img else None

                floor_plan_image_element = item.find(class_="casssetteitem_other-thumbnail")
                data["間取画像URL"] = floor_plan_image_element.img["rel"] if floor_plan_image_element and floor_plan_image_element.img else None

                property_link_element = item.select_one("a[href*='/chintai/jnc_']")
                data["物件詳細URL"] = "https://suumo.jp" +property_link_element['href'] if property_link_element else None

                # ここで各物件のデータを取得し、all_dataに追加
                all_data.append(data)

        # 1アクセスごとに3秒休む
        time.sleep(3)

    return all_data

# 築年数の加工
def process_construction_year(x):
    return 0 if x == '新築' else int(re.split('[築年]', x)[1])

# 構造：階建情報の取得
def get_most_floor(x):
    if '階建' not in x:
        return np.nan
    elif 'B' not in x:
        floor_list = list(map(int, re.findall(r'(\d+)階建', str(x))))
        return min(floor_list)
    else:
        return np.nan

# 階数の取得
def get_floor(x):
    if '階' not in x:
        return np.nan
    elif 'B' not in x:
        floor_list = list(map(int, re.findall(r'(\d+)階', str(x))))
        return min(floor_list)
    else:
        floor_list = list(map(int, re.findall(r'(\d+)階', str(x))))
        return -1 * min(floor_list)

# 費用の変換
def change_fee(x, unit):
    if unit not in x:
        return np.nan
    else:
        return float(x.split(unit)[0])

# 面積の変換
def process_area(x):
    return float(x[:-2])

# 住所の分割
def split_address(x, start, end):
    return x[x.find(start)+1:x.find(end)+1]

# アクセス情報の分割
def split_access(row):
    accesses = row['アクセス'].split(', ')
    results = {}

    for i, access in enumerate(accesses, start=1):
        if i > 3:
            break  # 最大3つのアクセス情報のみを考慮

        parts = access.split('/')
        if len(parts) == 2:
            line_station, walk = parts
            # ' 歩'で分割できるか確認
            if ' 歩' in walk:
                station, walk_min = walk.split(' 歩')
                # 歩数の分の数値だけを抽出
                walk_min = int(re.search(r'\d+', walk_min).group())
            else:
                station = None
                walk_min = None
        else:
            line_station = access
            station = walk_min = None

        results[f'アクセス①{i}線路名'] = line_station
        results[f'アクセス①{i}駅名'] = station
        results[f'アクセス①{i}徒歩(分)'] = walk_min

    return pd.Series(results)

# 漢数字と丁目のマッピング
kanji_map = str.maketrans({
    '1': '一丁目',
    '2': '二丁目',
    '3': '三丁目',
    '4': '四丁目',
    '5': '五丁目',
    '6': '六丁目',
    '7': '七丁目',
    '8': '八丁目',
    '9': '九丁目',
    '１': '一丁目',
    '２': '二丁目',
    '３': '三丁目',
    '４': '四丁目',
    '５': '五丁目',
    '６': '六丁目',
    '７': '七丁目',
    '８': '八丁目',
    '９': '九丁目',
})

def convert_address(address):
    return address.translate(kanji_map)


# 住所から緯度と経度を取得する関数
def get_lat_lon(address):
    geolocator = Nominatim(user_agent="myGeocoder")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    location = geocode(address)
    if location:
        return location.latitude, location.longitude
    return None, None

# データ加工のメイン関数
def process_real_estate_data(dataframe):
    """
    不動産データを加工する関数。
    Args:
    dataframe (pandas.DataFrame): 加工する不動産データが含まれるDataFrame
    Returns:
    pandas.DataFrame: 加工後のDataFrame
    """
    dataframe['築年数'] = dataframe['築年数'].apply(process_construction_year)
    dataframe['構造'] = dataframe['構造'].apply(get_most_floor)
    dataframe['階数'] = dataframe['階数'].apply(get_floor)
    dataframe['家賃'] = dataframe['家賃'].apply(lambda x: change_fee(x, '万円'))
    dataframe['敷金'] = dataframe['敷金'].apply(lambda x: change_fee(x, '万円'))
    dataframe['礼金'] = dataframe['礼金'].apply(lambda x: change_fee(x, '万円'))
    dataframe['管理費'] = dataframe['管理費'].apply(lambda x: change_fee(x, '円'))
    dataframe['面積'] = dataframe['面積'].apply(process_area)
    dataframe['区'] = dataframe['アドレス'].apply(lambda x: split_address(x, "都", "区"))
    dataframe['市町'] = dataframe['アドレス'].apply(lambda x: split_address(x, "区", ""))
    #dataframe['漢数字アドレス'] = dataframe['アドレス'].apply(convert_address)
    #dataframe['緯度'], dataframe['経度'] = zip(*dataframe['漢数字アドレス'].apply(get_lat_lon))

    dataframe = dataframe.join(dataframe.apply(split_access, axis=1))

    return dataframe


def main():
    # スクレイピング
    base_url = "https://suumo.jp/jj/chintai/ichiran/FR301FC001/?ar=030&bs=040&ta=13&sc=13101&sc=13102&cb=0.0&ct=9999999&et=9999999&cn=9999999&mb=0&mt=9999999&shkr1=03&shkr2=03&shkr3=03&shkr4=03&fw2=&srch_navi=1&page={}"# 千代田区,中央区
    max_page = 1
    print("1.スクレイピング開始", " : ページ数", max_page)
    scraped_data = scrape_real_estate_data(base_url, max_page)
    print("1.スクレイピング完了")

    # データフレームに変換
    df = pd.DataFrame(scraped_data)

    # 重複データの削除
    df = df.drop_duplicates()

    # データ加工
    print("2.不動産データの加工開始")
    processed_df = process_real_estate_data(df)
    print("2.不動産データの加工完了")

    # room.dbにアスセスする。
    dbname = 'DB/room.db'
    conn = sqlite3.connect(dbname)

    # room.dbにデータをSQLiteに渡す
    processed_df.to_sql('room_ver2',conn,if_exists='replace',index=None)

    # データベースへのコネクションを閉じる。(必須)
    conn.close()

    print("3.スクレイピング完了")

if __name__ == "__main__":
    main()
