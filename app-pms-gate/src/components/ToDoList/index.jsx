import React, { Component } from 'react';
import { Row, Col, Divider, Input } from 'antd';
import ToDoTable from './ToDoTable';
import './index.css';

const { Search } = Input;
export default class ToDoList extends Component {
  state = {
    searchText: "",
  };
  render() {
    return (
      <div className="todo">
        {/* Header */}
        <Row align="middle">
          <Col className="todo-title" span={10}>
            My Todos
          </Col>
          <Col span={14}>
            <Search
              placeholder="Filter Todos"
              allowClear
              enterButton
              onSearch={(v) =>
                this.setState({ searchText: v.trim() })
              }
            />
          </Col>
        </Row>
        <Divider style={{ margin: "8px 0" }}/>
        {/* Content */}
        <Row style={{ flex: 1, minHeight: 0 }}>
          <Col span={24} style={{ height: "100%", minHeight: 0 }}>
            <ToDoTable searchText={this.state.searchText} />
          </Col>
        </Row>
      </div>
    );
  }
}
