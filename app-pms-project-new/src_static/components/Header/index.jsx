import React, { Component } from 'react'
import { Avatar } from 'antd';
import './index.css'
import { Row, Col, Divider } from 'antd';
import Colorbar from '../../assets/bosch-colorbar.jpg';
import Logo from '../../assets/bosch-app-pms.jpg';
export default class Header extends Component {
  render() {
    const { user } = this.props;
    return (
      <div>
        <Row>
          <img src={Colorbar} alt="ColorBar" className="colorbar"/>
        </Row>
        <Row className='header' type="flex" justify="start">
          <Col span={8}>
            <img src={Logo} alt="Logo" className="logo" />
          </Col>
          <Col span={8} offset={8}>
            <Row span={24} type="flex" justify="end">
                <Avatar shape="square" style={{ backgroundColor: '#5da7e4ff' }}>{user.username.slice(0, 2).toUpperCase()}</Avatar>
            </Row>
          </Col>
        </Row>
      </div>

    );
  }
}

