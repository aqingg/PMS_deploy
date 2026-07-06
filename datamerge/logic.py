import httpx
import json
import asyncio
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Optional, Any

GATEWAY_KEY = "PN9rSrBi6770yG35WSoN25yAPiWaqbBS"
BASE_URL = "http://apiroutecccn.apac.bosch.com/openapi/pmsserverprod/api"

URL_STEP1 = f"{BASE_URL}/getSimpleProjectInfoList?gatewayKey={GATEWAY_KEY}"
URL_STEP2_TEMPLATE = f"{BASE_URL}/vms/get/CustomerProjectByIDX/{{uuid}}?gatewayKey={GATEWAY_KEY}"
URL_STEP3_TEMPLATE = f"{BASE_URL}/vms/pbi/CustomerProjects/ALL?projectId={{uuid}}"

def find_team_members_by_role(team_members, target_role):
    names = []
    if not isinstance(team_members, list):
        return names
    for member in team_members:
        if isinstance(member, dict) and member.get('Role') == target_role:
            full_name = member.get('USI', {}).get('FullName')
            if full_name:
                names.append(full_name)
            elif member.get('DisplayName'):
                names.append(member.get('DisplayName'))
    return names

def format_all_roles(team_members):
    if not isinstance(team_members, list):
        return "N/A"
    role_map = defaultdict(list)
    for member in team_members:
        if isinstance(member, dict) and member.get('Role') and member.get('DisplayName'):
            role_map[member['Role']].append(member['DisplayName'])
    if not role_map:
        return "N/A"
    return "; ".join([f"{role}: {', '.join(names)}" for role, names in sorted(role_map.items())])

def format_all_emails(team_members):
    if not isinstance(team_members, list):
        return "N/A"
    role_map = defaultdict(list)
    for member in team_members:
        if isinstance(member, dict) and member.get('Role') and member.get('DisplayName'):
            if isinstance(member.get('USI'), dict) and member.get('USI').get('Email'):
                member_email = f"{member['DisplayName']}_{member.get('USI').get('Email')}"
            else:
                member_email = f"{member['DisplayName']}_NoEmailInfo"
            role_map[member['Role']].append(member_email)
    if not role_map:
        return "N/A"
    return "; ".join([f"{role}Email: {', '.join(names)}" for role, names in sorted(role_map.items())])


async def fetch_project_identifiers() -> List[Dict[str, str]]:
    """
    仅获取并筛选项目列表，返回 UUID 和 customer_name 的列表。
    """
    async with httpx.AsyncClient() as client:
        try:
            response_step1 = await client.get(URL_STEP1, timeout=30)
            response_step1.raise_for_status()
            projects_data = response_step1.json()
        except (httpx.RequestError, json.JSONDecodeError) as e:
            print(f"错误: 无法获取项目列表。 {e}")
            raise

        filtered_projects = []
        if projects_data.get('data') and isinstance(projects_data['data'], list):
            for item in projects_data['data']:
                if item.get('product_category', '').startswith('AB1'):
                    filtered_projects.append({
                        "uuid": item.get('uuid'),
                        "customer": item.get('customer_name')
                    })
        return filtered_projects

async def fetch_single_project_details(uuid: str) -> Optional[Dict[str, Any]]:
    """
    根据单个UUID获取详细信息，返回一个 profile 字典。
    如果获取失败，则返回 None。
    """
    profile = {
        "customer": "N/A",
        "project": "N/A",
        "ab_generation": "N/A",
        "sop": 0,
        "vehicle_variant": "N/A",
        "plattform": "N/A",
        "type": "N/A",
        "vint_responsible": "N/A",
        "project_leader": "N/A",
        "region": "N/A",
        "oem": "N/A",
        "model": "N/A",
        "peripheral_sensor_configuration": "N/A",
        "internal_sensor_configuration": "N/A",
        "role_summary": "N/A",
        "Digit10OemPn": "N/A",
        "customerOemPn": "N/A",
        "FlConfiguration": "N/A",
        "TargetMarket": "N/A",
        "MCR_No": "N/A",
        "ConnectorDirection": "N/A",
        "Status": "N/A",

        "AlmProjectName": "N/A",
        "ReferenceProjectPn": "N/A",
        "ReferenceProjectBm": "N/A",
        "role_email_summary": "N/A"
    }

    async def get_step2_data(client):
        try:
            url_step2 = URL_STEP2_TEMPLATE.format(uuid=uuid)
            response = await client.get(url_step2, timeout=20)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, json.JSONDecodeError) as e:
            print(f"警告: Step 2 失败 (UUID: {uuid}): {e}")
            return None

    async def get_step3_data(client):
        try:
            url_step3 = URL_STEP3_TEMPLATE.format(uuid=uuid)
            headers = {'gatewayKey': GATEWAY_KEY}
            response = await client.get(url_step3, headers=headers, timeout=300)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, json.JSONDecodeError) as e:
            print(f"警告: Step 3 失败 (UUID: {uuid}): {e}")
            return None

    async with httpx.AsyncClient() as client:
        data2, data3 = await asyncio.gather(get_step2_data(client), get_step3_data(client))

    if data2:
        profile["customer"] = data2.get('CustomerName', 'N/A')
        profile["project"] = (data2.get('VehicleModelNameList') or ['N/A'])[0]
        profile["model"] = (data2.get('VehicleModelNameList') or ['N/A'])[0]
        profile["ab_generation"] = data2.get('ProductCategory', 'N/A')
        profile["type"] = data2.get('VehicleSegment', 'N/A')
        
        profile["Digit10OemPn"] = data2.get('Digit10OemPn', 'N/A')
        profile["customerOemPn"] = data2.get('customerOemPn', 'N/A')
        profile["TargetMarket"] = data2.get('TargetMarket', 'N/A')
        profile["Status"] = data2.get('Status', 'N/A')

        TeamMembers = data2.get('TeamMembers', [])
        profile["role_summary"] = format_all_roles(TeamMembers)

        sop_str = data2.get('TimelineObject', {}).get('CustomerSOP')
        if sop_str:
            try:
                dt_object = datetime.fromisoformat(sop_str.replace('Z', '+00:00'))
                profile["sop"] = int(dt_object.strftime('%Y%m%d'))
            except (ValueError, TypeError):
                profile["sop"] = 0
                
        profile['plattform'] = (data2.get('PlatformList') or ['N/A'])[0]
        profile["region"] = data2.get('respRegion', 'N/A')
        profile['vehicle_variant'] = (data2.get('VehicleModelNameList') or ['N/A'])[0]

    if data3:
        profile["oem"] = data3.get('CustomerName', 'N/A')
        profile["vint_responsible"] = data3.get('RespSWPCM', 'N/A')
        profile["project_leader"] = data3.get('RespTPM', 'N/A')
        
        all_sensors = [data3.get(key, '') for key in ['Ufs', 'Pas', 'Pps']]
        valid_parts = [s for s in all_sensors if s and s != '0']
        profile["peripheral_sensor_configuration"] = '+'.join(valid_parts) if valid_parts else 'N/A'
        
        profile["FlConfiguration"] = data3.get('FlConfiguration', 'N/A')

        profile["internal_sensor_configuration"] = data3.get('InternalSensor', 'N/A')
        profile["MCR_No"] = data3.get('MCR_L0', 'N/A')
        profile["ConnectorDirection"] = data3.get('ConnectorDirection', 'N/A')

        profile["AlmProjectName"] = data3.get('AlmProjectName', 'N/A')
        profile["ReferenceProjectPn"] = data3.get('ReferenceProjectPn', 'N/A')
        profile["ReferenceProjectBm"] = data3.get('ReferenceProjectBm','N/A')

        TeamMemberEmails = data3.get('TeamMembers', [])
        profile["role_email_summary"] = format_all_emails(TeamMemberEmails)

    for key, value in profile.items():
        if value == 'null' or value == None:
            profile[key] = 'N/A'
    
    return profile

async def fetch_all_project_details() -> List[Dict[str, Any]]:
    """
    获取所有项目的完整详细信息。
    """
    try:
        identifiers = await fetch_project_identifiers()
    except Exception as e:
        # 增加日志记录，以便了解为什么获取标识符会失败
        print(f"Error fetching project identifiers: {e}") 
        return []

    if not identifiers:
        return []

    tasks = [fetch_single_project_details(item['uuid']) for item in identifiers if item.get('uuid')]
    
    # 使用 return_exceptions=True 来收集所有结果，包括异常
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_project_profiles = []
    for res in results:
        if res is not None and not isinstance(res, Exception):
            # 结果是有效的数据，添加它
            all_project_profiles.append(res)
        elif isinstance(res, Exception):
            # 这是一个异常，记录下来以便调试
            # 在生产环境中，应该使用 logging 模块
            print(f"A task failed while fetching project details: {res}")
    
    return all_project_profiles
