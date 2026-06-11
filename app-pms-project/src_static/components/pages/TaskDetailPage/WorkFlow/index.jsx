import React from "react";
import { Row, Col, Button, Typography } from "antd";
import { ArrowRightOutlined } from "@ant-design/icons";

const { Text } = Typography;

export default function WorkFlow({ inputs, operation, outputs }) {
  const handleOperation = () => {
    console.log("POST →", operation.url);
    console.log("BODY →", operation.body);
  };

  return (
    <div style={{ marginTop: 40 }}>

      {/* ===================== TITLE ROW ===================== */}
      <Row align="middle" style={{ marginBottom: 16 }}>

        {/* ① INPUT TITLE — span=5 */}
        <Col span={5} style={{ textAlign: "center" }}>
          <Text strong style={{ fontSize: 16 }}>Inputs</Text>
        </Col>

        {/* ② ARROW COLUMN (empty title) — span=1 */}
        <Col span={1}></Col>

        {/* ③ OPERATION TITLE — span=12 */}
        <Col span={12} style={{ textAlign: "center" }}>
          <Text strong style={{ fontSize: 16 }}>Operation</Text>
        </Col>

        {/* ④ ARROW COLUMN (empty title) — span=1 */}
        <Col span={1}></Col>

        {/* ⑤ OUTPUT TITLE — span=5 */}
        <Col span={5} style={{ textAlign: "center" }}>
          <Text strong style={{ fontSize: 16 }}>Outputs</Text>
        </Col>

      </Row>


      {/* ===================== CONTENT ROW ===================== */}
      <Row align="middle">

        {/* ① INPUT COLUMN — span=5 */}
        <Col span={7}>
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                {inputs.map((inp, idx) => (
                <Button
                    key={idx}
                    block
                    type="default"
                    style={{
                    height: 48,
                    fontSize: 15,
                    borderRadius: 6,
                    justifyContent: "center",
                    }}
                >
                    {inp}
                </Button>
                ))}
            </div>
            </Col>


        {/* ② ARROW COLUMN — span=1 */}
        <Col span={1} style={{ textAlign: "center" }}>
          <ArrowRightOutlined style={{ fontSize: 24 }} />
        </Col>

        {/* ③ OPERATION COLUMN — span=12 */}
        <Col span={8} style={{ textAlign: "center" }}>
            <Button
                block               // ⭐ 让按钮宽度100%
                type="primary"
                onClick={handleOperation}
                style={{
                height: 48,
                fontSize: 15,
                borderRadius: 6,
                justifyContent: "center",
                }}
            >
                {operation.label}
            </Button>
            </Col>


        {/* ④ ARROW COLUMN — span=1 */}
        <Col span={1} style={{ textAlign: "center" }}>
          <ArrowRightOutlined style={{ fontSize: 24 }} />
        </Col>

        {/* ⑤ OUTPUT COLUMN — span=5 */}
        <Col span={7}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {outputs.map((out, idx) => (
            <Button
                key={idx}
                block
                type="default"
                style={{
                height: 48,
                fontSize: 15,
                borderRadius: 6,
                justifyContent: "center",
                }}
            >
                {out}
            </Button>
            ))}
        </div>
        </Col>
      </Row>
    </div>
  );
}
