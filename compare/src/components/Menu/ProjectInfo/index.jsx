import React, { useMemo } from 'react';
import { Typography, Button, Space } from 'antd';
import { EditOutlined, FormOutlined } from '@ant-design/icons';
import ProgressBar from '../ProgressBar';
import { useAppContext } from "../../../context/AppContext";

const { Title, Text } = Typography;

export default function ProjectInfo() {

  const { projectInfo, projectName } = useAppContext();

  const handleEdit = () => {
    window.location.hash = "#/edit";
  };

  // ⭐ 计算填写比例
  const projectProgress = useMemo(() => {
    if (!projectInfo) return 0;

    let total = 0;
    let filled = 0;

    // 1) projectInfo.projectInfo（二维数组）
    if (Array.isArray(projectInfo.projectInfo)) {
      projectInfo.projectInfo.forEach(row => {
        row.forEach(item => {
          total++;
          if (item.value && item.value.trim() !== "") filled++;
        });
      });
    }

    // 2) owner
    if (projectInfo.owner) {
      total++;
      if (projectInfo.owner.value && projectInfo.owner.value.trim() !== "") filled++;
    }

    // 3) proxies
    if (projectInfo.proxies) {
      total++;
      if (projectInfo.proxies.value && projectInfo.proxies.value.trim() !== "") filled++;
    }

    if (total === 0) return 0;
    return Math.round((filled / total) * 100);

  }, [projectInfo]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 16 }}>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Title level={4} style={{ margin: 0 }}>
          {projectName || "Unknown Project"}
        </Title>

        <Button type="text" icon={<EditOutlined />} onClick={handleEdit}>
          Edit
        </Button>
      </div>

      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        <Text type="secondary" style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
          <FormOutlined /> Completeness of project information
        </Text>

        <ProgressBar percent={projectProgress} />
      </Space>

    </div>
  );
}
