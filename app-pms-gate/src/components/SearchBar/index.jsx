import React, { useContext, useEffect, useMemo, useState } from "react";
import { Row, Col, Input, Button, Tooltip, AutoComplete, message, Space } from "antd";
import { LinkOutlined, ExportOutlined } from "@ant-design/icons";
import { AppContext } from "../../context/AppContext";
import "./index.css";

export default function SearchBar() {
  const { links, loadLinks, openTodoLink } = useContext(AppContext);

  const [inputValue, setInputValue] = useState("");

  const resolveFirstLink = () => {
    const keyword = inputValue.trim().toLowerCase();

    const candidates = keyword
      ? links.filter(l =>
          l.title.toLowerCase().includes(keyword)
        )
      : links;

    return candidates[0] || null;
  };

  // 部署时加载 links
  useEffect(() => {
    loadLinks();
  }, [loadLinks]);

  // 根据 input 实时过滤候选项
  const options = useMemo(() => {
    if (!inputValue) {
    return links.map((l) => ({
      value: l.title,
      link: l,
    }));
    }

    const keyword = inputValue.toLowerCase();

    return links
      .filter((l) => l.title.toLowerCase().includes(keyword))
    .map((l) => ({
      value: l.title,
      link: l,
    }));
  }, [links, inputValue]);

  const [selectedLink, setSelectedLink] = useState(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  return (
    <div className="search">
      <Row align="middle">
        <Col className="search-title" span={6}>
          Quick Links
        </Col>

        <Col span={18}>
          <AutoComplete
            options={options}
            value={inputValue}
            onChange={(val) => {
              setInputValue(val);
              setSelectedLink(null);
            }}
            onSelect={(value, option) => {
              setInputValue(value);       // 同步输入
              setSelectedLink(option.link); // 记录选择
            }}
            onDropdownVisibleChange={(open) => {
              setDropdownOpen(open);
            }}
            style={{ width: "100%" }}
          >
        <Input.Search
          placeholder="Filter Links"
          allowClear
          enterButton={
            <Space size={4}>
              {/* Open */}
              <Tooltip title="Open Link">
                <Button
                  type="primary"
                  icon={<ExportOutlined />}
                  size="small"
                  onClick={() => {
                    const link = selectedLink || resolveFirstLink();
                    if (!link) return;
                    openTodoLink(link.linkage);
                  }}
                />
              </Tooltip>
              {/* Copy */}
              <Tooltip title="Copy Link">
                <Button
                  type="primary"
                  icon={<LinkOutlined />}
                  size="small"
                  onClick={async () => {
                    const link = resolveFirstLink();
                    if (!link) return;

                    try {
                      await navigator.clipboard.writeText(link.linkage);
                      message.success("Copied Link to Clipboard");
                    } catch {
                      message.error("Copy failed");
                    }
                  }}
                />
              </Tooltip>
            </Space>
          }
        onKeyDown={(e) => {
          if (e.key !== "Enter") return;

        // ⭐ dropdown 打开时：只做 select，不 open
        if (dropdownOpen) return;

          const link = selectedLink || resolveFirstLink();
          if (!link) return;

          openTodoLink(link.linkage);
        }}
        />
          </AutoComplete>
        </Col>
      </Row>
    </div>
  );
}
