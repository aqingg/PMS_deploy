import React from "react";
import { Input, Form } from "antd";

export default function ProjectInfoFill({ label, value, onChange }) {
  return (
    <Form.Item
      label={label}
      labelAlign="left"
      labelCol={{ style: { width: 120 } }}
      wrapperCol={{ style: { flex: 1 } }}
      style={{ marginBottom: 12 }}
    >
      <Input
        value={value}                     // ⭐ 受控组件
        onChange={(e) => onChange(e.target.value)}   // ⭐ 向父组件传递更新
        style={{ height: 32 }}
      />
    </Form.Item>
  );
}
