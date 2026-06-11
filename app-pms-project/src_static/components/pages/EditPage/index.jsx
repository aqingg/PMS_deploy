import React, { useState, useEffect } from "react";
import {
  Button,
  Modal,
  Divider,
  Input,
  Row,
  Col,
  Form,
  Select,
  message,
} from "antd";
import { ImportOutlined, ExportOutlined } from "@ant-design/icons";
import ProjectInfoFill from "./ProjectInfoFill";

export default function EditProjectPage({ user, projectName }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [filterText, setFilterText] = useState("");

  const [messageApi, contextHolder] = message.useMessage();

  // ⭐ 项目基础信息（假数据）
  const [projectInfoData, setProjectInfoData] = useState(null);
  const [loading, setLoading] = useState(true);

  const [ownerValue, setOwnerValue] = useState("");
  const [proxiesValue, setProxiesValue] = useState("");
  const [infoValues, setInfoValues] = useState([]);

  // =================================================================================
  // ⭐ 加载假数据
  // =================================================================================
  useEffect(() => {
    async function loadProjectInfo() {
      console.log("📡 EditProjectPage 使用假数据，不调用后端");

      // ======== ⭐ 模拟后端结构的 FAKE DATA ============
      const fakeData = {
        owner: { label: "Owner", value: "John Doe" },
        proxies: { label: "Proxies", value: "Alice / Bob" },
        projectInfo: [
          [
            { label: "Project Code", value: "PRJ-1001" },
            { label: "Version", value: "v1.0" }
          ],
          [
            { label: "Start Date", value: "2025-01-10" },
            { label: "End Date", value: "2025-03-31" },
            { label: "Priority", value: "High" }
          ],
          [
            { label: "Customer", value: "Internal" },
            { label: "Region", value: "APAC" },
            { label: "Tag", value: "Core Module" },
            { label: "Type", value: "Development" }
          ]
        ],
      };

      // 模拟加载延迟
      setTimeout(() => {
        setProjectInfoData(fakeData);

        setOwnerValue(fakeData.owner.value);
        setProxiesValue(fakeData.proxies.value);

        // 二维表单初始化
        setInfoValues(
          fakeData.projectInfo.map((row) => row.map((item) => item.value))
        );

        setLoading(false);
      }, 300);
    }

    loadProjectInfo();
  }, [user, projectName]);

  // =================================================================================
  // ⏳ Loading 处理
  // =================================================================================
  if (loading) return <div>Loading Project Info...</div>;
  if (!projectInfoData) return <div>No Project Info Found</div>;

  const { projectInfo, owner, proxies } = projectInfoData;

  // =================================================================================
  // ⭐ 二维动态表单渲染
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
              value={infoValues[rowIndex][colIndex]}
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

  // =================================================================================
  // ⭐ 模拟保存 Update Project Info（不调用后端）
  // =================================================================================
  async function rewriteProjectInfo() {
    const finalData = {
      owner: { label: owner.label, value: ownerValue },
      proxies: { label: proxies.label, value: proxiesValue },
      projectInfo: projectInfo.map((row, rIdx) =>
        row.map((item, cIdx) => ({
          label: item.label,
          value: infoValues[rIdx][cIdx],
        }))
      ),
    };

    console.log("✔ 模拟保存成功（假数据）:", finalData);

    messageApi.success({
      content: "Project Info Updated! (Fake Save)",
      duration: 2,
    });

    // 模拟刷新（和后端保持行为一致）
    window.location.hash = "#/?" + Date.now();
  }

  // =================================================================================
  // ⭐ Page UI
  // =================================================================================
  return (
    <div style={{ position: "relative" }}>
      {contextHolder}

      {/* Header */}
      <Row align="middle">
        <Col flex="auto">
          <h1 className="text-2xl font-bold m-0">{projectName}</h1>
        </Col>

        <Col flex="none">
          <div style={{ display: "flex", gap: 12 }}>
            <Button
              type="default"
              style={{ height: 40, width: 200, fontSize: 16, fontWeight: 600 }}
              icon={<ImportOutlined style={{ fontSize: 20 }} />}
              onClick={() => setModalOpen(true)}
            >
              Import From PMS
            </Button>

            <Button
              type="primary"
              style={{ height: 40, width: 200, fontSize: 16, fontWeight: 600 }}
              icon={<ExportOutlined style={{ fontSize: 20 }} />}
              onClick={rewriteProjectInfo}
            >
              Update Project Info
            </Button>
          </div>
        </Col>
      </Row>

      <Divider />

      {/* Main Form */}
      <Form layout="horizontal" style={{ width: "100%" }}>
        <Row gutter={24} style={{ marginBottom: 8 }}>
          <Col span={12}>
            <Form.Item label={owner.label} labelCol={{ style: { width: 120 } }}>
              <Input
                value={ownerValue}
                onChange={(e) => setOwnerValue(e.target.value)}
                style={{ height: 32 }}
              />
            </Form.Item>
          </Col>

          <Col span={12}>
            <Form.Item label={proxies.label} labelCol={{ style: { width: 120 } }}>
              <Input
                value={proxiesValue}
                onChange={(e) => setProxiesValue(e.target.value)}
                style={{ height: 32 }}
              />
            </Form.Item>
          </Col>
        </Row>

        <Divider />

        {/* 二维渲染 */}
        {projectInfo.map((row, index) => renderRow(row, index))}
      </Form>
    </div>
  );
}
