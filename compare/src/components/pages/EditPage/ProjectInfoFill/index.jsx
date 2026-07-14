import React from "react";
import { Input, Form, Select } from "antd";

export default function ProjectInfoFill({ label, value, keys, onChange }) {
  const hasKeys = Array.isArray(keys) && keys.length > 0;
  return (
    <Form.Item
      label={label}
      style={{ marginBottom: 12 }}
    >
      {hasKeys ? (
        <Select
          mode="multiple"
          value={Array.isArray(value) ? value : value ? value.split(",").map(v => v.trim()) : []}
          onChange={(val) => {
            // ⭐ 核心：数组 → string
            onChange(val.join(", "));
          }}
          style={{ width: "100%", height: 32 }}
          options={keys.map((k) => ({
            label: k,
            value: k,
          }))}
          allowClear
        />
      ) : (
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{ height: 32 }}
        />
      )}
    </Form.Item>
  );
}
