#!/usr/bin/env python3
"""人民法院诉讼资产网 - 拍卖公告爬虫 (Playwright 浏览器版)
使用无头浏览器绕过反爬, 提取结构化数据"""
import json, os, sys, re, time
from datetime import datetime
from urllib.parse import urljoin

DATA_FILE = 'data/auctions.json'
STATS_FILE = 'data/stats.json'
FIRST_RUN_FLAG = 'data/.first_run'
BASE_URL = "https://www1.rmfysszc.gov.cn/News/Pmgg.shtml?fid=5186&dh=3&st=0"
DETAIL_BASE = "https://www.rmfysszc.gov.cn"


def init_browser():
    """初始化 Playwright 浏览器"""
    try:
        from playwright.sync_api import sync_playwright
        print("[INFO] 启动 Playwright 浏览器...")
        p = sync_playwright().start()
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        return p, browser, page
    except ImportError:
        print("[ERROR] 未安装 playwright, 请运行: pip install playwright && playwright install chromium")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 浏览器启动失败: {e}")
        sys.exit(1)


def fetch_list_page(page, page_num=1):
    """使用浏览器获取列表页"""
    url = f"{BASE_URL}&page={page_num}"
    print(f"[INFO] 浏览器访问列表页 {page_num}: {url}")
    try:
        page.goto(url, wait_until='networkidle', timeout=30000)
        # 等待表格加载
        page.wait_for_selector('table tr', timeout=10000)
        html = page.content()
        print(f"[DEBUG] 列表页HTML长度: {len(html)}")
        return html
    except Exception as e:
        print(f"[ERROR] 列表页 {page_num} 加载失败: {e}")
        return None


def fetch_detail_page(page, url):
    """使用浏览器获取详情页"""
    print(f"[INFO] 浏览器访问详情页: {url}")
    try:
        page.goto(url, wait_until='networkidle', timeout=30000)
        html = page.content()
        print(f"[DEBUG] 详情页HTML长度: {len(html)}")
        return html
    except Exception as e:
        print(f"[ERROR] 详情页加载失败: {e}")
        return None


def parse_list(html):
    """解析列表页HTML"""
    if not html:
        print("[WARN] HTML为空")
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    auctions = []

    # 找 tr.listtr
    rows = soup.find_all('tr', class_='listtr')
    print(f"[DEBUG] 找到 {len(rows)} 个 tr.listtr")

    # 备用筛选
    if not rows:
        all_tr = soup.find_all('tr')
        for tr in all_tr:
            tds = tr.find_all('td')
            if len(tds) >= 3 and tds[0].find('a'):
                rows.append(tr)
        print(f"[DEBUG] 备用筛选后: {len(rows)} 个 tr")

    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 3:
            continue
        link_tag = cols[0].find('a')
        if not link_tag:
            continue
        title = link_tag.get('title', '') or link_tag.get_text(strip=True)
        link = link_tag.get('href', '')
        if link and not link.startswith('http'):
            link = urljoin(DETAIL_BASE, link)

        court = ''
        if len(cols) > 1:
            court_tag = cols[1].find('span', class_='n_c_l')
            court = court_tag.get('title', '') if court_tag else cols[1].get_text(strip=True)

        pub_date = ''
        if len(cols) > 2:
            date_tag = cols[2].find('span', class_='n_c_r')
            pub_date = date_tag.get_text(strip=True) if date_tag else cols[2].get_text(strip=True)

        auctions.append({
            'id': link.split('/')[-1].replace('.shtml', '') if link else '',
            'title': title, 'link': link, 'court': court, 'pub_date': pub_date,
        })

    return auctions


def parse_detail(html, base_info):
    """解析详情页"""
    result = {
        'community': '', 'building': '', 'total_floor': '', 'current_floor': '',
        'area': '', 'start_price': '', 'jd_link': '', 'auction_time': '',
        'location': '', 'certificate_no': '', 'usage': '', 'deposit': '', 'remark': ''
    }
    if not html:
        return result

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text()
    title = base_info.get('title', '')

    # 京东链接
    m = re.search(r'https?://sifa\.jd\.com/\d+', text)
    if m: result['jd_link'] = m.group(0)

    # 拍卖时间
    for pat in [
        r'(\d{4}年\d{1,2}月\d{1,2}日\d{1,2}时(?:至|—)\d{4}年\d{1,2}月\d{1,2}日\d{1,2}时)',
        r'将于\s*(\d{4}年\d{1,2}月\d{1,2}日.*?10时)',
    ]:
        m = re.search(pat, text)
        if m:
            result['auction_time'] = m.group(1).replace('\n', '').strip()
            break

    # 小区名
    for pat in [
        r'关于.*?([\u4e00-\u9fa5]{2,}(?:小区|花园|广场|大厦|公寓|苑|郡|城|府|里|园|庭|阁|居|坊|墅|湾|岛|湖|山))',
        r'关于.*?([\u4e00-\u9fa5]{2,}路\d+号[\u4e00-\u9fa5]{2,})'
    ]:
        m = re.search(pat, title)
        if m:
            result['community'] = m.group(1)
            break

    # 楼栋
    m = re.search(r'(\d+幢)', title)
    if m: result['building'] = m.group(1)

    # 面积
    for pat in [
        r'证载建筑面积[：:]\s*(\d+\.?\d*)\s*平方米',
        r'建筑面积[：:]\s*(\d+\.?\d*)\s*[㎡m²]',
        r'(\d+\.?\d*)\s*平方米'
    ]:
        m = re.search(pat, text)
        if m:
            result['area'] = m.group(1) + '㎡'
            break

    # 楼层
    for pat in [
        r'所在层数?[/／]总层数?[：:]\s*(\d+)[/／](\d+)',
        r'所在层[/／]总楼层[：:]\s*(\d+)[/／](\d+)',
    ]:
        m = re.search(pat, text)
        if m:
            result['current_floor'] = m.group(1) + '层'
            result['total_floor'] = m.group(2) + '层'
            break

    # 起拍价
    for pat in [
        r'起拍价[：:]\s*([\d,\.]+)\s*万元',
        r'起拍价[：:]\s*([\d,\.]+)\s*元',
        r'变卖价[：:]\s*([\d,\.]+)\s*(?:万元|元)'
    ]:
        m = re.search(pat, text)
        if m:
            ps = m.group(1).replace(',', '')
            if '万元' in m.group(0):
                result['start_price'] = ps + '万元'
            else:
                v = float(ps)
                result['start_price'] = f"{v/10000:.2f}万元" if v > 10000 else ps + '元'
            break

    # 保证金
    m = re.search(r'保证金[：:]\s*([\d,\.]+)\s*(?:万元|元)', text)
    if m:
        result['deposit'] = m.group(1).replace(',', '') + ('万元' if '万元' in m.group(0) else '元')

    # 产权证号
    m = re.search(r'不动产证书号[：:]\s*([^，。\n]+)', text)
    if m: result['certificate_no'] = m.group(1).strip()

    # 规划用途
    m = re.search(r'规划用途[：:]\s*([^，。\n]+)', text)
    if m: result['usage'] = m.group(1).strip()

    # 表格补充
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 2:
                lbl = cells[0].get_text(strip=True)
                if '坐落' in lbl and not result['location']:
                    result['location'] = cells[1].get_text(strip=True)
                if '建筑面积' in lbl and not result['area']:
                    mm = re.search(r'(\d+\.?\d*)', cells[1].get_text(strip=True))
                    if mm: result['area'] = mm.group(1) + '㎡'
                if '所在层' in lbl and not result['current_floor']:
                    mm = re.search(r'(\d+)[/／](\d+)', cells[1].get_text(strip=True))
                    if mm:
                        result['current_floor'] = mm.group(1) + '层'
                        result['total_floor'] = mm.group(2) + '层'

    # 标题补充
    if not result['current_floor']:
        mm = re.search(r'(\d{3,4})室', title)
        if mm:
            r = mm.group(1)
            result['current_floor'] = r[0:2] + '层' if len(r) == 4 else r[0] + '层'
    if not result['location']:
        mm = re.search(r'([\u4e00-\u9fa5]{2,}路\d+号)', title)
        if mm: result['location'] = mm.group(1)

    return result


def is_first_run():
    return not os.path.exists(FIRST_RUN_FLAG)

def mark_first_run_complete():
    with open(FIRST_RUN_FLAG, 'w') as f:
        f.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def merge_data(existing, new_items):
    ed = {item['id']: item for item in existing}
    for item in new_items:
        if item.get('id'):
            old = ed.get(item['id'], {})
            item['crawl_count'] = old.get('crawl_count', 0) + 1
            item['first_seen'] = old.get('first_seen', item.get('crawl_time'))
            ed[item['id']] = item
    merged = list(ed.values())
    merged.sort(key=lambda x: x.get('pub_date', ''), reverse=True)
    return merged

def save_data(data):
    os.makedirs('data', exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 已保存 {len(data)} 条")

def save_stats(data):
    stats = {
        'total': len(data), 'by_court': {}, 'by_type': {}, 'by_community': {},
        'total_area': 0, 'total_start_price': 0,
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    for item in data:
        stats['by_court'][item.get('court', '未知')] = stats['by_court'].get(item.get('court', '未知'), 0) + 1
        stats['by_type'][item.get('auction_type', '未知')] = stats['by_type'].get(item.get('auction_type', '未知'), 0) + 1
        stats['by_community'][item.get('community', '未知')] = stats['by_community'].get(item.get('community', '未知'), 0) + 1
        try:
            stats['total_area'] += float(item.get('area', '').replace('㎡', '')) if item.get('area') else 0
        except:
            pass
        try:
            ps = item.get('start_price', '').replace('万元', '').replace('元', '').replace(',', '')
            v = float(ps) if ps else 0
            if '万元' in item.get('start_price', ''): v *= 10000
            stats['total_start_price'] += v
        except:
            pass
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    return stats


def main():
    print(f"[{datetime.now()}] 开始爬取...")

    # 初始化浏览器
    p, browser, page = init_browser()

    first_run = is_first_run()
    max_pages = 10 if first_run else 3
    print(f"[INFO] {'首次部署' if first_run else '增量更新'}, 爬取 {max_pages} 页")

    existing = load_existing()
    print(f"[INFO] 已有: {len(existing)} 条")

    all_new = []
    try:
        for pg in range(1, max_pages + 1):
            print(f"[INFO] 列表页 {pg}/{max_pages}...")
            html = fetch_list_page(page, pg)
            if not html:
                print("[WARN] 获取HTML失败,跳过")
                continue
            items = parse_list(html)
            if not items:
                print(f"[INFO] 第{pg}页无数据,停止")
                break
            print(f"[INFO] 第{pg}页 {len(items)} 条, 解析详情...")

            for i, item in enumerate(items, 1):
                print(f"  [{i}/{len(items)}] {item['title'][:40]}...")
                detail_html = fetch_detail_page(page, item['link'])
                detail = parse_detail(detail_html, item)

                atype = ''
                t = item['title']
                if '第一次拍卖' in t: atype = '第一次拍卖'
                elif '第二次拍卖' in t: atype = '第二次拍卖'
                elif '变卖' in t: atype = '变卖'
                elif '重新一拍' in t: atype = '重新一拍'

                all_new.append({
                    **item, 'auction_type': atype,
                    'community': detail['community'], 'building': detail['building'],
                    'total_floor': detail['total_floor'], 'current_floor': detail['current_floor'],
                    'area': detail['area'], 'start_price': detail['start_price'],
                    'deposit': detail['deposit'], 'jd_link': detail['jd_link'],
                    'auction_time': detail['auction_time'],
                    'location': detail['location'] or detail['community'],
                    'certificate_no': detail['certificate_no'], 'usage': detail['usage'],
                    'remark': detail['remark'],
                    'crawl_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'crawl_count': 1,
                    'first_seen': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                time.sleep(1.5)
    finally:
        browser.close()
        p.stop()

    merged = merge_data(existing, all_new)
    save_data(merged)
    stats = save_stats(merged)

    if first_run and len(merged) > 0:
        mark_first_run_complete()
        print("[INFO] 首次部署标记完成")

    print(f"[{datetime.now()}] 完成! 共 {len(merged)} 条")
    print(f"[STATS] 总面积:{stats['total_area']:.1f}㎡ 总起拍价:{stats['total_start_price']/10000:.1f}万")
    return 0


if __name__ == '__main__':
    sys.exit(main())
