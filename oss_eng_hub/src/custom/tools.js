export const toolItems = [
  {
    key: 'home',
    title: '首页',
    desc: '工具总览与快速入口。',
    path: '/',
    icon: 'pi pi-home'
  },
  {
    key: 'util-reviewer',
    title: 'Util JSON Reviewer',
    desc: '通用 JSON 审查与结构检查。',
    path: '/Util_JSON_reviewer',
    toolPath: 'Util_JSON_reviewer',
    icon: 'pi pi-search'
  },
  {
    key: 'sys_upload_crs_to_doors',
    title: 'CRS上传至DOORS',
    desc: '将CRS数据上传至DOORS系统，确保数据一致性和可追溯性。',
    path: '/sys_upload_crs_to_doors',
    toolPath: 'sys_upload_crs_to_doors',
    icon: 'pi pi-home'
  },
  {
    key: 'System_Document_Generator',
    title: 'Document生成器',
    desc: '根据系统数据自动生成文档，提升文档编写效率和质量。',
    path: '/System_Document_Generator',
    toolPath: 'System_Document_Generator',
    icon: 'pi pi-home'
  },{
    key: 'doors_upload_util',
    title: 'Doors上传系统',
    desc: '将数据上传至DOORS系统，确保数据的完整性和可追溯性。',
    path: '/doors_upload_util',
    toolPath: 'doors_upload_util',
    icon: 'pi pi-home'
  },
  {
    key: 'APP-PMS-GATE',
    title: 'APP-PMS-GATE的门户网页',
    desc: 'EPD5使用的门户网页，提供project列表查看。',
    path: '/APP-PMS-GATE',
    toolPath: 'APP-PMS-GATE',
    icon: 'pi pi-home'
  },
    {
    key: 'APP-PMS-Project',
    title: 'APP-PMS-Project详细内容',
    desc: 'Project信息的详细工作流网页。',
    path: '/APP-PMS-Project',
    toolPath: 'APP-PMS-Project',
    icon: 'pi pi-home'
  }
]

export const portalTools = toolItems.filter((item) => item.path !== '/')