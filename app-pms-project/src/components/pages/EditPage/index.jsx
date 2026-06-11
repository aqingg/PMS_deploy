import React, { useState, useEffect } from "react";
import {
  Button,
  Divider,
  Input,
  Row,
  Col,
  Form,
  message,
  Modal,
  Select,
} from "antd";
import { ImportOutlined, ExportOutlined, LinkOutlined  } from "@ant-design/icons";
import { useAppContext } from "../../../context/AppContext";
import ProjectInfoFill from "./ProjectInfoFill";

export default function EditProjectPage() {
  const { user, projectName, projectId, projectInfo, rewriteProjectInfo, SetUpApplicationFloder, 
    teamMembers, loadTeamMembers, getProjectInfoFromPMS, getProjectFromPMS } =
    useAppContext();

  // modal 开关
  const [ownerModalVisible, setOwnerModalVisible] = useState(false);
  const [proxiesModalVisible, setProxiesModalVisible] = useState(false);

  // 多选数据
  const [proxiesSelected, setProxiesSelected] = useState([]);

  const [messageApi, contextHolder] = message.useMessage();

  // ⭐ 可编辑状态（初始化来自 context）
  const [ownerValue, setOwnerValue] = useState("");
  const [proxiesValue, setProxiesValue] = useState("");
  const [infoValues, setInfoValues] = useState([]);
  const [ownerFilter] = useState("");
  const [proxiesFilter] = useState("");

  const [uuidValue, setUuidValue] = useState("");

  const [pmsData, setPmsData] = useState([]);
  const [customerModalVisible, setCustomerModalVisible] = useState(false);
  const [projectModalVisible, setProjectModalVisible] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [selectedProject, setSelectedProject] = useState(null);

  // 按首字母排序（忽略大小写）
  const sortedMembers = [...teamMembers].sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase())
  );

  // Owner 过滤
  const ownerFiltered = sortedMembers.filter((name) =>
    name.toLowerCase().includes(ownerFilter.toLowerCase())
  );

  // Proxies 过滤
  const proxiesFiltered = sortedMembers.filter((name) =>
    name.toLowerCase().includes(proxiesFilter.toLowerCase())
  );

  function openOwnerModal() {
    loadTeamMembers();
    setOwnerModalVisible(true);
  }

  function openProxiesModal() {
    loadTeamMembers();

    // ⭐ 把之前的 proxiesValue 解析回数组
    if (proxiesValue) {
      const arr = proxiesValue.split(",").map(v => v.trim());
      setProxiesSelected(arr);
    }

    setProxiesModalVisible(true);
  }

  // ⭐ 初始化：把 context 值转为可编辑值
  useEffect(() => {
    if (!projectInfo) return;

    // owner / proxies / uuid
    setOwnerValue(projectInfo.owner?.value ?? "");
    setProxiesValue(projectInfo.proxies?.value ?? "");
    setUuidValue(projectInfo.uuid?.value ?? "");

    // 二维数组
    if (Array.isArray(projectInfo.projectInfo)) {
      setInfoValues(
        projectInfo.projectInfo.map((row) =>
          row.map((item) => {
            const v = item.value;
            // ⭐ 统一转成 string
            if (Array.isArray(v)) {
            return v.join(", ");
            }
          return v ?? "";
        })
        )
      );
    }
  }, [projectInfo, projectName]);

  if (!projectInfo) return <div>Loading Project Info...</div>;

  const grid = projectInfo.projectInfo || [];
  const owner = projectInfo.owner || { label: "Owner", value: "" };
  const proxies = projectInfo.proxies || { label: "Proxies", value: "" };
  const uuid = projectInfo.uuid || {label: "UUID", value: "" };

  // =================================================================================
  // ⭐ 二维表单行渲染
  // =================================================================================
  const renderRow = (row, rowIndex) => {
    const count = row.length;

    let span = 24;
    if (count === 2) span = 12;
    else if (count === 3) span = 8;
    else if (count === 4) span = 6;
    else if (count > 4) span = 3;

    return (
      <Row key={rowIndex} gutter={24} style={{ marginBottom: 12 }}>
        {row.map((item, colIndex) => (
          <Col span={span} key={colIndex}>
            <ProjectInfoFill
              label={item.label}
              value={infoValues[rowIndex]?.[colIndex] ?? ""}
              keys={item.keys}
              onChange={(val) => {
                const newInfo = [...infoValues];
                newInfo[rowIndex][colIndex] = val;
                setInfoValues(newInfo);
              }}
            />
          </Col>
        ))}
      </Row>
    );
  };

  function isValidUrl(string) {
    // 如果链接不是必需的，这里返回 true
    if (!string) {
      return false; 
    }
    try {
      new URL(string);
      return true;
    } catch (_) {
      return false;
    }
  }

  async function handleSave() {
    const projectInfoData = grid.map((row, rIdx) =>
      row.map((item, cIdx) => ({
        ...item,
        value: infoValues[rIdx][cIdx],
      }))
    );

    const publicLinkValue = projectInfoData
      .flat()
      .find(item => item.label === 'Public Link')
      ?.value;

    if (isValidUrl(publicLinkValue)) {
      try {
        const result = await SetUpApplicationFloder(publicLinkValue);
        //const result = await SetUpApplicationFloder("C:/Users/SZO8SZH/Downloads/testoutput/");
        if(result = "success") {
          messageApi.success("Create Floder Success");
        } else {
          messageApi.error("Failed to create floder");
        }
      } catch (error) {
      messageApi.destroy();
      console.error("Error while saving project info:", error);
      messageApi.error("An unexpected error occurred. Please check the console.");
      }
    }

    const finalData = {
      username: user.username,
      department: user.department,
      projectId,
      projectName,
      projectInfo: {
        owner: { label: owner.label, value: ownerValue },
        proxies: { label: proxies.label, value: proxiesValue },
        uuid: { label: uuid.label, value: uuidValue },
        projectInfo: projectInfoData,
      },
    };

    try {
      messageApi.loading('Updating project info...', 0);
      const result = await rewriteProjectInfo(finalData);
      messageApi.destroy();

      if (result.success) {
        messageApi.success("Project Info Updated!");
      } else {
        messageApi.error(result.message || "Failed to update project info");
      }
    } catch (error) {
      messageApi.destroy();
      console.error("Error while saving project info:", error);
      messageApi.error("An unexpected error occurred. Please check the console.");
    }
  };

  async function handleExportFile() {
    const projectId = localStorage.getItem('projectId');

    if (!projectId) {
      console.error('在 LocalStorage 中未找到 projectId');
      messageApi.error('无法导出文件，项目ID丢失！');
      return;
    }

    const apiUrl = `http://127.0.0.1:7175/GeneralInfo/${projectId}`; 

    try {
      const response = await fetch(apiUrl, {
        method: 'GET',
      });

      if (!response.ok) {
        const errorData = await response.json(); 
        console.error('API返回错误:', errorData.detail || `HTTP status ${response.status}`);
        throw new Error(errorData.detail || `服务器错误: ${response.status}`);
      }

      const successData = await response.json();
      console.log('API调用成功，后端返回信息:', successData);
      
      messageApi.success('文件已在服务器端成功生成！');

    } catch (error) {
      console.error('导出文件时发生错误:', error);
      message.destroy();
      messageApi.error(`导出失败: ${error.message}`);
    }
  }

  function handleAutoFillLinks() {
    const newInfo = [...infoValues];

    let oemValue = "";
    let localPos = null;
    let publicPos = null;

    // 1. 先找到 OEM / Local Link / Public Link 的位置
    grid.forEach((row, rIdx) => {
      row.forEach((cell, cIdx) => {
        if (cell.label === "OEM") {
          oemValue = newInfo[rIdx][cIdx] || "";
        }
        if (cell.label === "Local Link") {
          localPos = { rIdx, cIdx };
        }
        if (cell.label === "Public Link") {
          publicPos = { rIdx, cIdx };
        }
      });
    });

    // 2. OEM 必须存在
    if (!oemValue) {
      messageApi.error("Please fill OEM first.");
      return;
    }

    // ⭐ 3. 清理 OEM 和 projectName：空格 & "." → "_"
    const safeOEM = oemValue.replace(/[\s.]/g, "_");
    const safeProjectName = projectName.replace(/[\s.]/g, "_");

    // ⭐ 4. 自动构造路径（使用 "\"）
    const baseA = "C:\\AppTools\\00.APP-PMS\\PlayGround";
    const baseB = "\\\\bosch.com\\dfsrb\\DfsCN\\DIV\\CC\\Prj\\PS\\00_General\\10_Migrated_2_ILM\\99_PlayGround";

    const localPath = `${baseA}\\${safeOEM}\\${safeProjectName}`;
    const publicPath = `${baseB}\\${safeOEM}\\${safeProjectName}`;

    // 5. 写入路径
    if (localPos) {
      newInfo[localPos.rIdx][localPos.cIdx] = localPath;
    }
    if (publicPos) {
      newInfo[publicPos.rIdx][publicPos.cIdx] = publicPath;
    }

    // 6. 更新前端 state
    setInfoValues(newInfo);

    // ⭐⭐⭐ 7. 自动保存项目（触发 Update Project Info）
    handleSave();
  };


  async function linktoPMS() {
    if (!uuidValue) {
      messageApi.warning("Please select a project first.");
      return;
    }

    try {
      const Baseurl = "https://cccn.apac.bosch.com/pms/#/WorkSpace_AddEditProject";
      const url = `${Baseurl}?projectid=${uuidValue}`;

      window.open(url, '_blank', 'noopener,noreferrer');
    }catch (error) {
      console.error("An unexpected error occurred while trying to link to PMS:", error);
      messageApi.error("An unexpected error occurred. Please try again or contact support.");
    }
  };

  const pmsToFormKeyMap = {
    "OEM": "oem",
    "Product Category": "ab_generation",
    "Market": "TargetMarket",
    "Status": "Status",
    "SOP Date": "sop",

    "Project Leader":"project_leader",
    "MCR No.": "MCR_No",
    "ECU Direction": "ConnectorDirection",
    "BOSCH PIN": "Digit10OemPn",
    "Customer PIN": "customerOemPn",

    "Inertial Sensor": "internal_sensor_configuration",
    "Peripheral Sensor": "peripheral_sensor_configuration",
    "Vehicle Type": "type",

    "Fire Loops": "FlConfiguration"
  };

  async function handleImportFromPMS() {
    if (!uuidValue) {
      messageApi.warning("Please get a UUID from PMS first.");
      return;
    }

    try {
      // 获取项目信息
      messageApi.loading('Importing from PMS...');
      const pmsProjectDetail = await getProjectInfoFromPMS(uuidValue);

      // 检查返回值
      if (!pmsProjectDetail || Object.keys(pmsProjectDetail).length === 0) {
        messageApi.warning('No details found for this UUID in PMS.');
        return;
      }
      
      // 数据更新
      const newInfo = infoValues.map(row => [...row]); 

      const labelToCoordMap = new Map();
      grid.forEach((row, rIdx) => {
        row.forEach((cell, cIdx) => {
          labelToCoordMap.set(cell.label, [rIdx, cIdx]);
        });
      });

      for (const formLabel in pmsToFormKeyMap) {
        const pmsKey = pmsToFormKeyMap[formLabel];

        // 检查 PMS 数据中是否存在这个 key
        if (pmsProjectDetail.data.hasOwnProperty(pmsKey)) {
          // 从坐标映射中查找该 label 对应的位置
          const coords = labelToCoordMap.get(formLabel);
          
          if (coords) {
            const [rIdx, cIdx] = coords;
            let pmsValue = pmsProjectDetail.data[pmsKey];

            // 格式化数据
            if (pmsValue === null || pmsValue === undefined || pmsValue === "") {
              pmsValue = "N/A";
            } else if (Array.isArray(pmsValue)) {
              pmsValue = pmsValue.join(", ");
            } else {
              pmsValue = String(pmsValue);
            }

            // 更新 newInfo
            newInfo[rIdx][cIdx] = pmsValue;
          }
        }
      }

      // 使用更新后的数据
      setInfoValues(newInfo);

      messageApi.success('Project Info successfully imported from PMS!');
    } catch (error) {
      console.error("Error fetching from PMS:", error);
      messageApi.error('Failed to fetch data from PMS.');
    }
  };

  async function getUUIDFromPMS() {
    try {
      const pmsItems = await getProjectFromPMS();
      if (pmsItems && pmsItems.length > 0) {
        setPmsData(pmsItems);
        setSelectedCustomer(null);
        setSelectedProject(null);
        setCustomerModalVisible(true);
      } else {
        messageApi.warning("No data found from PMS.");
      }
    } catch (error) {
      console.error("Error fetching from PMS:", error);
      messageApi.error("Failed to fetch data from PMS.");
    }
  };

  function handleCustomerSelectOk() {
    if (selectedCustomer) {
      setCustomerModalVisible(false);
      setProjectModalVisible(true);
    } else {
      messageApi.warning("Please select a customer.");
    }
  };

  function handleProjectSelectOk() {
    if (selectedCustomer && selectedProject) {
      const selectedItem = pmsData.find(
        (item) =>
          item.customer_name === selectedCustomer &&
          item.project_name === selectedProject
      );

      if (selectedItem && selectedItem.uuid) {
        setUuidValue(selectedItem.uuid);
        messageApi.success("UUID has been imported from PMS!");
      } else {
        messageApi.error("Could not find a matching UUID for the selected project.");
      }
      
      handleModalCancel();
    } else {
      messageApi.warning("Please select a project.");
    }
  };

  function handleModalCancel() {
      setCustomerModalVisible(false);
      setProjectModalVisible(false);
      setSelectedCustomer(null);
      setSelectedProject(null);
      setPmsData([]);
  };

  // 过滤重复的 customer_name
  const customerOptions = Array.from(new Set(pmsData.map(item => item.customer_name)))
    .filter(Boolean) // 过滤掉空值
    .sort()
    .map(name => ({ label: name, value: name }));

  // 根据选择的 customer 获取对应的 project_name
  const projectOptions = pmsData
    .filter(item => item.customer_name === selectedCustomer)
    .map(item => ({ label: item.project_name, value: item.project_name }))
    .sort((a, b) => a.label.localeCompare(b.label));


  // =================================================================================
  // ⭐ UI
  // =================================================================================
  return (
    <div style={{ position: "relative" }}>
      {contextHolder}

      <Row align="middle">
        <Col flex="auto">
          <h1 className="text-2xl font-bold m-0">{projectName}</h1>
        </Col>

        <Col flex="none">
          <div style={{ display: "flex", gap: 12 }}>
            
            {/* Auto Fill Links */}
            <Button
              type="default"
              style={{
                height: 40,
                width: 180,
                fontSize: 13,
                fontWeight: 600,
              }}
              icon={<LinkOutlined style={{ fontSize: 20 }} />}
              onClick={handleAutoFillLinks}
            >
              Auto Fill Links
            </Button>

            {/* Import From PMS */}
            <Button
              type="default"
              style={{
                height: 40,
                width: 150,
                fontSize: 13,
                fontWeight: 600,
              }}
              icon={<ImportOutlined style={{ fontSize: 20 }} />}
              onClick={handleImportFromPMS}
            >
              Import From PMS
            </Button>

            {/* Jump To PMS */}
            <Button 
              type="primary"
              style={{
                height: 40,
                width: 150,
                fontSize: 13,
                fontWeight: 600,
              }}
              icon={<ExportOutlined style={{ fontSize: 20 }} />}
              onClick={linktoPMS}
            >
              Jump To PMS
            </Button>

            {/* Export Filled Template */}
            <Button
              type="primary"
              style={{
                height: 40,
                width: 150,
                fontSize: 13,
                fontWeight: 600,
              }}
              icon={<ExportOutlined style={{ fontSize: 20 }} />}
              onClick={handleExportFile}
            >
              Export File
            </Button>

            {/* Update */}
            <Button
              type="primary"
              style={{
                height: 40,
                width: 150,
                fontSize: 13,
                fontWeight: 600,
              }}
              icon={<ExportOutlined style={{ fontSize: 20 }} />}
              onClick={handleSave}
            >
              Update Project Info
            </Button>

          </div>
        </Col>

      </Row>
      <Divider />

      {/* 主表单 */}
      <Form
        layout="horizontal"
        labelCol={{ style: { width: 150 } }}
        wrapperCol={{ style: { width: "calc(100% - 150px)" } }}
        style={{ width: "100%" }}
      >
        <Row gutter={24} style={{ marginBottom: 8 }}>
          <Col span={12}>
            <Form.Item
              label={owner.label}
            >
              <Input
                value={ownerValue}
                readOnly
                onClick={openOwnerModal}
                style={{ height: 32, background: "#f5f5f5", cursor: "pointer" }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              label={proxies.label}
            >
              <Input
                value={proxiesValue}
                readOnly
                onClick={openProxiesModal}
                style={{ height: 32, background: "#f5f5f5", cursor: "pointer" }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              label={uuid.label}
            >
              <Input
                value={uuidValue}
                readOnly
                onClick={getUUIDFromPMS}
                style={{ height: 32, background: "#f5f5f5", cursor: "pointer" }}
              />
            </Form.Item>
          </Col>
        </Row>
        <Divider />
        {grid.map((row, index) => renderRow(row, index))}
      </Form>

      <Modal
        title="Step 1: Select Customer"
        open={customerModalVisible}
        onOk={handleCustomerSelectOk}
        onCancel={handleModalCancel}
        destroyOnHidden
      >
        <p style={{marginTop: 16, marginBottom: 8}}>Please select the customer name from the PMS data.</p>
        <Select
          showSearch
          style={{ width: "100%" }}
          placeholder="Search or select a customer"
          value={selectedCustomer}
          onChange={(value) => {
            setSelectedCustomer(value);
            setSelectedProject(null);
          }}
          options={customerOptions}
        />
      </Modal>

      <Modal
        title="Step 2: Select Project"
        open={projectModalVisible}
        onOk={handleProjectSelectOk}
        onCancel={handleModalCancel}
        destroyOnHidden
      >
        <div style={{marginTop: 16, marginBottom: 8}}>
            <p>
                Customer: <strong>{selectedCustomer}</strong>
            </p>
            <p>Please select the project name to import its UUID.</p>
        </div>
        <Select
          showSearch
          style={{ width: "100%" }}
          placeholder="Search or select a project"
          value={selectedProject}
          onChange={(value) => setSelectedProject(value)}
          options={projectOptions}
        />
      </Modal>

      <Modal
        title="Select Owner"
        open={ownerModalVisible}
        onCancel={() => setOwnerModalVisible(false)}
        onOk={() => setOwnerModalVisible(false)}
      >
        <Select
          showSearch
          style={{ width: "100%" }}
          value={ownerValue}
          onChange={(val) => setOwnerValue(val)}
          options={ownerFiltered.map((name) => ({ label: name, value: name }))}
        />
      </Modal>

      <Modal
        title="Select Proxies"
        open={proxiesModalVisible}
        onCancel={() => setProxiesModalVisible(false)}
        onOk={() => {
          setProxiesValue(proxiesSelected.join(", "));
          setProxiesModalVisible(false);
        }}
      >
        <Select
          mode="multiple"
          allowClear
          showSearch
          style={{ width: "90%" }}
          value={proxiesSelected}
          onChange={(val) => setProxiesSelected(val)}
          options={proxiesFiltered.map((name) => ({ label: name, value: name }))}
        />
      </Modal>

    </div>
  );
}
