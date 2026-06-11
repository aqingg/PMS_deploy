import React, { useState } from "react";
import { Row, Col, Button, Typography } from "antd";
import { ArrowRightOutlined, /* MoreOutlined */ } from "@ant-design/icons";
import SidebarRight from "./SidebarRight";  // ⭐ 你自己写的 sidebar-right 组件

const { Text } = Typography;

/* -------------------------------------------
   ⭐ IOItem —— 单个 Input / Output 项
   带 hover 时从右侧滑出 SidebarRight
--------------------------------------------- */
function IOItem({ label, taskId, projectName, user }) {
  const [hover, setHover] = useState(false);

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {/* 主按钮 */}
      <Button
        block
        type="default"
        style={{
          height: 48,
          fontSize: 15,
          borderRadius: 6,
          textAlign: "left",
          paddingLeft: 50,
        }}
      >
        {label}
      </Button>

      {/* ⭐ SidebarRight：贴在按钮左侧，从左向右展开 */}
      {hover && (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            height: "100%",
          }}
        >
          <SidebarRight
            itemLabel={label}
            taskId={taskId}
            projectName={projectName}
            user={user}
          />
        </div>
      )}
    </div>
  );
}


/* -------------------------------------------
   ⭐ WorkFlow 主组件
--------------------------------------------- */
export default function WorkFlow({
  inputs = [],
  outputs = [],
  operation = null,
  operationLabel = "Execute",
  onOperationClick = null,

  // ⭐ TaskDetailPage 传进来的
  taskId,
  projectName,
  user
}) {
  const safeInputs = inputs.map((item) =>
    typeof item === "string" ? item : item?.label
  );

  const safeOutputs = outputs.map((item) =>
    typeof item === "string" ? item : item?.label
  );

  const isManual = operationLabel === "Manual Operation";

  return (
    <div style={{ marginTop: 40 }}>
      {/* 标题部分 */}
      <Row align="middle" style={{ marginBottom: 16 }}>
        <Col span={5} style={{ textAlign: "center" }}>
          <Text strong style={{ fontSize: 16 }}>Inputs</Text>
        </Col>

        <Col span={1}></Col>

        <Col span={12} style={{ textAlign: "center" }}>
          <Text strong style={{ fontSize: 16 }}>Operation</Text>
        </Col>

        <Col span={1}></Col>

        <Col span={5} style={{ textAlign: "center" }}>
          <Text strong style={{ fontSize: 16 }}>Outputs</Text>
        </Col>
      </Row>

      {/* 内容 */}
      <Row align="middle">
        {/* INPUTS */}
        <Col span={7}>
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {safeInputs.map((label, idx) => (
              <IOItem 
                key={idx}
                label={label}
                taskId={taskId}
                projectName={projectName}
                user={user}
              />
            ))}
          </div>
        </Col>

        {/* Arrow */}
        <Col span={1} style={{ textAlign: "center" }}>
          <ArrowRightOutlined style={{ fontSize: 24 }} />
        </Col>

        {/* OPERATION */}
        <Col span={8} style={{ textAlign: "center" }}>
          <Button
            block
            disabled={isManual}
            type={isManual ? "default" : "primary"}
            onClick={() => {
              if (onOperationClick) {
                onOperationClick(operation);
              }
            }}
            style={{
              height: 48,
              fontSize: 15,
              borderRadius: 6,
              justifyContent: "center",
              background: isManual ? "#d9d9d9" : undefined,
              color: isManual ? "#555" : undefined,
              cursor: isManual ? "not-allowed" : "pointer",
            }}
          >
            {operationLabel}
          </Button>
        </Col>

        {/* Arrow */}
        <Col span={1} style={{ textAlign: "center" }}>
          <ArrowRightOutlined style={{ fontSize: 24 }} />
        </Col>

        {/* OUTPUTS */}
        <Col span={7}>
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {safeOutputs.map((label, idx) => (
              <IOItem 
                key={idx}
                label={label}
                taskId={taskId}
                projectName={projectName}
                user={user}
              />
            ))}
          </div>
        </Col>
      </Row>
    </div>
  );
}

