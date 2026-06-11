import React, { useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Divider, Input, Row, Col, Form, Select, Card, Steps, message, theme } from "antd";
import { ImportOutlined , ExportOutlined } from "@ant-design/icons";
import WorkFlow from "./WorkFlow";

export default function TaskDetailPage() {
  const { taskName } = useParams();

  // ⭐ 工作流步骤（假数据）
  // ⭐ 工作流步骤（后端未来将返回的结构格式）
  const steps = [
    {
      title: "Created",

      // 输入（未来后端提供）
      inputs: ["User_A created task", "Initial requirements"],

      // 操作按钮需要执行的网络请求（未来你可以真正调用）
      operation: {
        label: "Verify Creation",
        url: "/api/task/verifyCreated",
        body: { step: "created", task: taskName }
      },

      // 输出（后端或下一步返回）
      outputs: ["Task record created", "Task ID assigned"]
    },

    {
      title: "Reviewed",

      inputs: ["Review checklist", "Documents uploaded by User_A"],

      operation: {
        label: "Approve Review",
        url: "/api/task/approveReview",
        body: { step: "reviewed", task: taskName }
      },

      outputs: ["Review accepted", "Request forwarded to processing team"]
    },

    {
      title: "Processing",

      inputs: ["Processing documents", "Assigned engineer information"],

      operation: {
        label: "Mark as Processed",
        url: "/api/task/markProcessed",
        body: { step: "processing", task: taskName }
      },

      outputs: ["Intermediate results", "Processing logs"]
    },

    {
      title: "Completed",

      inputs: ["Final validation documents"],

      operation: {
        label: "Archive Task",
        url: "/api/task/archiveTask",
        body: { step: "completed", task: taskName }
      },

      outputs: ["Archived task", "Completion certificate"]
    }
  ];


  // ⭐ 当前步骤
  const [current, setCurrent] = useState(0);
  const { token } = theme.useToken();

  const next = () => setCurrent(current + 1);
  const prev = () => setCurrent(current - 1);

  const items = steps.map((item) => ({
    key: item.title,
    title: item.title,
  }));

  const contentStyle = {
    padding: 16,
    marginTop: 16,
    background: token.colorFillAlter,
    border: `1px dashed ${token.colorBorder}`,
    borderRadius: token.borderRadiusLG,
    color: token.colorTextTertiary,
    lineHeight: "24px",
    fontSize: 14
  };

  
  return (
    <div>
      {/* Header */}
      <Row align="middle">
        <Col flex="auto">
          <h1 className="text-2xl font-bold m-0">{taskName}</h1>
        </Col>

        <Col flex="none">
          <div style={{ display: "flex", gap: 12 }}>
            <Button
              type="default"
              style={{
                height: 40,
                width: 150,
                fontSize: 16,
                fontWeight: 600,
              }}
              icon={<ImportOutlined style={{ fontSize: 20 }} />}
            >
              Set Declined
            </Button>
          </div>
        </Col>
      </Row>

      <Divider />

      {/* ⭐ COMMENT BLOCK */}
      <Card
        size="small"
        bordered={false}
        style={{
          marginTop: 12,
          marginBottom: 24,
          background: "#fafafa",
          borderRadius: 6,
        }}
      >
        <div
          style={{
            background: "#f5f5f5",
            padding: "12px 16px",
            borderRadius: 4,
            color: "#555",
            fontSize: 15,
            lineHeight: 1.6,
          }}
        >
          这是提示，用于指引用户操作.
          <br />
          这是具体的提示，用于用户学习
        </div>
      </Card>
      <Divider />
      {/* ⭐ WORKFLOW SECTION */}
      <Steps current={current} items={items} />
      <WorkFlow
        inputs={steps[current].inputs}
        operation={steps[current].operation}
        outputs={steps[current].outputs}
      />
      <div style={{ marginTop: 24 }}>
        {current < steps.length - 1 && (
          <Button type="primary" onClick={next}>
            Next
          </Button>
        )}
        {current === steps.length - 1 && (
          <Button type="primary" onClick={() => message.success("Workflow complete!")}>
            Done
          </Button>
        )}
        {current > 0 && (
          <Button style={{ margin: "0 8px" }} onClick={prev}>
            Previous
          </Button>
        )}
      </div>
      <Divider />
      <h2>Personal Comments</h2>
    </div>
  );
}
